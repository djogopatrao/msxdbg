"""Public session facade and execution state machine."""
from __future__ import annotations
from typing import Optional, Tuple

from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import Resolution, ResolutionStatus
from msxdbg.target.api import ExecutionStatus, PageState, Target, TargetError
from .breakpoints import BreakpointManager, BreakpointRecord, MappingQualifier
from .execution import (CancellationToken, Clock, ExecutionController,
                        ExecutionKind, ExecutionRequest)
from .frames import BacktraceResult, Frame, FrameService
from .inspection import StopInspectionContext
from .results import (CloseReport, DisassemblyResult, InvalidSessionState,
                      MemoryWriteResult, MutationVerificationError,
                      RegisterWriteResult, ResolvedTarget, StopResult, TargetQuery)
from .safety import (ConfirmationPermit, DangerousAction, InteractiveEntry,
                     SafetyGate, SignatureGuard)
from .memory_map import DEFAULT_PAGE3_POLICY, MemoryMapService
from .state import (SelectionState, SessionConfig, SessionState, StepMode,
                    StopCache, StopSnapshot)


class Session:
    def __init__(self, project: Project, target: Target, config: SessionConfig,
                 safety: SafetyGate, clock: Clock) -> None:
        self._project=project; self._target=target; self._config=config
        self._safety=safety; self._clock=clock
        self._signature_guard=SignatureGuard(config.signature)
        self._memory_map_service=MemoryMapService()
        self._state=SessionState.DISCONNECTED; self._mode=config.initial_mode
        self._breakpoint_manager=BreakpointManager(target)
        self._execution_controller=ExecutionController(target, project, clock)
        self._snapshot: Optional[StopSnapshot]=None
        self._stop_id=0; self._memory_epoch=0; self._saved_state: Optional[str]=None
        self._memory_cache = {}
        self._frame_service = FrameService(project, config.frame_limit)
        self._stop_cache = StopCache()
        self._selection: Optional[SelectionState] = None

    @property
    def state(self): return self._state
    @property
    def mode(self): return self._mode

    def attach(self) -> SessionState:
        if self._state == SessionState.CLOSED: raise InvalidSessionState("session is closed")
        return self.reconcile()

    def reconcile(self) -> SessionState:
        if self._state == SessionState.CLOSED: return self._state
        status=self._target.execution_status()
        self._state=SessionState.RUNNING if status == ExecutionStatus.RUNNING else SessionState.STOPPED
        if self._state == SessionState.STOPPED: self._capture_stop()
        self._breakpoint_manager.reconcile()
        return self._state

    def resolve_target(self, query: TargetQuery) -> Resolution[ResolvedTarget]:
        if query.address is not None:
            locations=self._project.resolve(query.address, query.image)
            description=f"{query.address:#06x}"
            candidates=(ResolvedTarget(query.address, locations, description),)
            return Resolution(ResolutionStatus.UNIQUE, candidates, locations.diagnostics)
        if query.symbol is not None:
            symbols=self._project.lookup_symbol(query.symbol, query.image)
            candidates=tuple(ResolvedTarget(s.address, self._project.resolve(s.address, query.image), s.name)
                             for s in symbols.candidates)
            return Resolution(symbols.status, candidates, symbols.diagnostics)
        lines=self._project.resolve_line(query.path, query.line, query.image)
        candidates=tuple(ResolvedTarget(m.location.address,
            self._project.resolve(m.location.address, query.image), query.path,
            m.effective_line) for m in lines.candidates)
        return Resolution(lines.status, candidates, lines.diagnostics)

    def execute(self, request: ExecutionRequest, cancel: CancellationToken) -> StopResult:
        if self._state not in (SessionState.RUNNING, SessionState.STOPPED):
            raise InvalidSessionState("session is not attached")
        if request.mode == StepMode.SOURCE and self._mode == StepMode.ASSEMBLY:
            request=ExecutionRequest(request.kind, request.address, self._mode, request.timeout_seconds)
        return self._execution_controller.run(request, self, cancel)

    def continue_until_signature(self, timeout_seconds: Optional[float],
                                 cancel: CancellationToken) -> StopResult:
        if self._config.signature is None:
            raise InvalidSessionState("continue --until-signature requires a configured signature")
        if timeout_seconds is None or timeout_seconds <= 0:
            raise ValueError("continue --until-signature requires a finite positive timeout")
        if self._state not in (SessionState.RUNNING, SessionState.STOPPED):
            raise InvalidSessionState("session is not attached")
        if (self._state == SessionState.STOPPED and self._snapshot is not None
                and self._snapshot.signature_status == "verified"):
            return self.where()
        last = None
        deadline = self._clock.monotonic() + timeout_seconds
        for _ in range(self._config.signature_attempt_limit):
            if cancel.is_cancelled():
                current = last or self.where()
                return StopResult(current.snapshot, current.matching_breakpoints,
                                  "cancelled", current.warnings)
            remaining = deadline - self._clock.monotonic()
            if remaining <= 0:
                raise TimeoutError("signature wait timed out; last confirmed state is preserved")
            request = ExecutionRequest(ExecutionKind.CONTINUE,
                                       timeout_seconds=remaining)
            last = self._execution_controller.run(request, self, cancel)
            if last.snapshot.signature_status == "verified":
                return last
            if cancel.is_cancelled():
                return StopResult(last.snapshot, last.matching_breakpoints,
                                  "cancelled", last.warnings)
        assert last is not None and self._state == SessionState.STOPPED
        raise TimeoutError(
            f"signature was not verified after {self._config.signature_attempt_limit} stops; target is stopped"
        )

    def invalidate(self) -> None:
        self._snapshot=None; self._memory_cache.clear(); self._stop_cache=StopCache()
        self._selection=None; self._memory_epoch+=1; self._state=SessionState.RUNNING

    def capture_stop(self) -> StopResult:
        snapshot=self._capture_stop()
        return StopResult(snapshot, self._breakpoint_manager.matching(snapshot.registers.get("PC")))

    def _capture_stop(self) -> StopSnapshot:
        registers=self._target.read_registers(); pc=registers.get("PC")
        self._stop_id+=1
        signature=self._signature_guard.check(self._target).value
        pages=self._target.read_pages() if self._project.mappings else ()
        active_image=self._project.image_for_pages(pages,pc) if pages else None
        self._snapshot=StopSnapshot(self._stop_id,self._memory_epoch,registers,
                                    self._project.resolve(pc,active_image),signature,
                                    pages=pages)
        self._stop_cache = StopCache()
        self._selection = SelectionState(self._stop_id, 0)
        self._state=SessionState.STOPPED
        return self._snapshot

    def where(self) -> StopResult:
        if self._state != SessionState.STOPPED: raise InvalidSessionState("target is not stopped")
        if self._snapshot is None: self._capture_stop()
        return StopResult(self._snapshot, self._breakpoint_manager.matching(self._snapshot.registers.get("PC")))

    def inspection(self):
        if self._state != SessionState.STOPPED or self._snapshot is None:
            raise InvalidSessionState("inspection requires a stopped target")
        trace = self.backtrace()
        if self._selection is None or self._selection.stop_id != self._snapshot.stop_id:
            self._selection = SelectionState(self._snapshot.stop_id, 0)
        frame = trace.frames[self._selection.frame_index]
        return StopInspectionContext(
            self._snapshot, frame, self._target, self._memory_cache,
            self._frame_service, self._inspection_is_current,
        )

    def _inspection_is_current(self, stop_id: int) -> bool:
        return (self._state == SessionState.STOPPED and self._snapshot is not None
                and self._snapshot.stop_id == stop_id)

    def backtrace(self):
        if self._state != SessionState.STOPPED or self._snapshot is None:
            raise InvalidSessionState("backtrace requires a stopped target")
        if not self._stop_cache.frames:
            result = self._frame_service.walk(self._snapshot, self._target)
            self._stop_cache.frames = result.frames
            self._stop_cache.frame_termination_reason = result.termination_reason
        return BacktraceResult(
            self._stop_cache.frames,
            self._stop_cache.frame_termination_reason or "unknown",
        )

    def select_frame(self, index: int):
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValueError("frame index must be an integer")
        trace = self.backtrace()
        if not 0 <= index < len(trace.frames):
            raise IndexError(f"frame index out of range: {index}")
        assert self._snapshot is not None
        self._selection = SelectionState(self._snapshot.stop_id, index)
        return trace.frames[index]

    def add_breakpoint(self,target:ResolvedTarget,condition:Optional[str]=None,
                       remote_condition:Optional[str]=None,
                       qualifier:Optional[MappingQualifier]=None)->BreakpointRecord:
        if qualifier is not None:
            if getattr(self._target.capabilities, "mapping_conditions", None) is False:
                raise InvalidSessionState("target does not support mapping-qualified breakpoints")
            pages=self._target.read_pages()
            page=qualifier.page if qualifier.page is not None else target.address // 0x4000
            observed=pages[page]
            if qualifier.segment is not None and observed.segment == "unknown":
                raise InvalidSessionState("target has no observable mapper segment for the qualified page")
        return self._breakpoint_manager.create(target, condition, remote_condition, qualifier)
    def add_watchpoint(self,access:str,address:int,size:int,
                       condition:Optional[str]=None)->BreakpointRecord:
        return self._breakpoint_manager.create_watchpoint(access,address,size,condition)
    def delete_breakpoint(self,number:int)->None: self._breakpoint_manager.delete(number)
    def suspend_breakpoint(self,number:int)->BreakpointRecord: return self._breakpoint_manager.suspend(number)
    def resume_breakpoint(self,number:int)->BreakpointRecord: return self._breakpoint_manager.resume(number)
    def breakpoints(self)->Tuple[BreakpointRecord,...]: return self._breakpoint_manager.records()

    def disassemble(self,address:int,count:int)->DisassemblyResult:
        instructions=self._target.disassemble(address,count)
        annotations=tuple(self._project.resolve(item.address) for item in instructions)
        pc=self._snapshot.registers.get("PC") if self._snapshot else self._target.read_registers().get("PC")
        return DisassemblyResult(instructions,annotations,pc,instructions[-1].address+instructions[-1].size)

    def pages(self)->Tuple[PageState,...]: return self._target.read_pages()
    def page3(self, policy):
        return self._memory_map_service.page3(
            self.inspection(), self._project, policy or DEFAULT_PAGE3_POLICY)
    def _begin_state_mutation(self) -> None:
        if self._state != SessionState.STOPPED or self._snapshot is None:
            raise InvalidSessionState("state mutation requires a stopped target")
        self._snapshot=None; self._memory_cache.clear(); self._stop_cache=StopCache()
        self._selection=None; self._memory_epoch+=1; self._state=SessionState.UNKNOWN

    def write_memory(self, address: int, data: bytes) -> MemoryWriteResult:
        data = bytes(data)
        if not data:
            raise ValueError("memory write requires at least one byte")
        if not isinstance(address, int) or isinstance(address, bool) or address < 0 \
                or address + len(data) > 0x10000:
            raise ValueError("memory write range is outside CPU memory")
        self._begin_state_mutation()
        spec = self._config.signature
        if spec is not None and address < spec.address + len(spec.expected) \
                and spec.address < address + len(data):
            self._signature_guard.rearm()
        try:
            self._target.write_memory(address, data)
        except TargetError as error:
            if not error.outcome_unknown:
                try: self._capture_stop()
                except Exception: self._state = SessionState.UNKNOWN
            raise
        try:
            observed = self._target.read_memory(address, len(data))
            snapshot = self._capture_stop()
        except Exception as error:
            self._state = SessionState.UNKNOWN
            raise MutationVerificationError(
                "memory write was accepted but verification failed", "write_memory") from error
        return MemoryWriteResult(address, data, observed, snapshot)

    def write_register(self, name: str, value: int) -> RegisterWriteResult:
        if not name or not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("register write requires a name and integer value")
        # Validate the name and width against the current, complete register set
        # before invalidating anything or issuing the mutation.
        if self._state != SessionState.STOPPED or self._snapshot is None:
            raise InvalidSessionState("state mutation requires a stopped target")
        width = self._snapshot.registers.width(name)
        if not 0 <= value < (1 << width):
            raise ValueError("register value is outside its width")
        self._begin_state_mutation()
        try:
            self._target.write_register(name, value)
        except TargetError as error:
            if not error.outcome_unknown:
                try: self._capture_stop()
                except Exception: self._state = SessionState.UNKNOWN
            raise
        try:
            snapshot = self._capture_stop()
            observed = snapshot.registers.get(name)
        except Exception as error:
            self._state = SessionState.UNKNOWN
            raise MutationVerificationError(
                "register write was accepted but verification failed", "write_register") from error
        return RegisterWriteResult(name.upper(), value, observed, snapshot)
    def set_mode(self,mode:StepMode)->None: self._mode=mode
    def save(self)->None:
        self._saved_state=f"msxdbg-{self._memory_epoch}"
        self._target.save_state(self._saved_state)
    def authorize(self, action: DangerousAction,
                  entry: InteractiveEntry) -> ConfirmationPermit:
        return self._safety.authorize_typed(action, entry)
    def reset(self,permit:ConfirmationPermit)->None:
        self._safety.consume(permit,DangerousAction.RESET)
        self._signature_guard.rearm(); self.invalidate(); self._target.reset()
    def load(self,permit:ConfirmationPermit)->None:
        self._safety.consume(permit,DangerousAction.LOAD)
        if self._saved_state is None: raise InvalidSessionState("no saved state")
        self._signature_guard.rearm(); self.invalidate(); self._target.load_state(self._saved_state)
    def close(self)->CloseReport:
        if self._state == SessionState.CLOSED: return CloseReport()
        report=self._breakpoint_manager.cleanup()
        self._target.close(); self._state=SessionState.CLOSED; self._snapshot=None
        return report


__all__=["Session"]
