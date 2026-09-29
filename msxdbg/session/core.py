"""Public session facade and execution state machine."""
from __future__ import annotations
from typing import Optional, Tuple

from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import Resolution, ResolutionStatus
from msxdbg.target.api import ExecutionStatus, PageState, Target
from .breakpoints import BreakpointManager, BreakpointRecord
from .execution import CancellationToken, Clock, ExecutionController, ExecutionRequest
from .frames import BacktraceResult, Frame, FrameService
from .inspection import StopInspectionContext
from .results import (CloseReport, DisassemblyResult, InvalidSessionState,
                      ResolvedTarget, StopResult, TargetQuery)
from .safety import (ConfirmationPermit, DangerousAction, InteractiveEntry,
                     SafetyGate, SignatureStatus)
from .state import (SelectionState, SessionConfig, SessionState, StepMode,
                    StopCache, StopSnapshot)


class Session:
    def __init__(self, project: Project, target: Target, config: SessionConfig,
                 safety: SafetyGate, clock: Clock) -> None:
        self._project=project; self._target=target; self._config=config
        self._safety=safety; self._clock=clock
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

    def invalidate(self) -> None:
        self._snapshot=None; self._memory_cache.clear(); self._stop_cache=StopCache()
        self._selection=None; self._memory_epoch+=1; self._state=SessionState.RUNNING

    def capture_stop(self) -> StopResult:
        snapshot=self._capture_stop()
        return StopResult(snapshot, self._breakpoint_manager.matching(snapshot.registers.get("PC")))

    def _capture_stop(self) -> StopSnapshot:
        registers=self._target.read_registers(); pc=registers.get("PC")
        self._stop_id+=1
        signature=SignatureStatus.NOT_CONFIGURED.value
        if self._config.signature is not None:
            spec=self._config.signature
            signature=(SignatureStatus.VERIFIED.value if self._target.read_memory(spec.address,len(spec.expected)) == spec.expected
                       else SignatureStatus.PENDING.value)
        self._snapshot=StopSnapshot(self._stop_id,self._memory_epoch,registers,
                                    self._project.resolve(pc),signature)
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

    def add_breakpoint(self,target:ResolvedTarget)->BreakpointRecord: return self._breakpoint_manager.create(target)
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
        raise NotImplementedError("page-3 analysis belongs to the memory-map phase")
    def set_mode(self,mode:StepMode)->None: self._mode=mode
    def save(self)->None:
        self._saved_state=f"msxdbg-{self._memory_epoch}"
        self._target.save_state(self._saved_state)
    def authorize(self, action: DangerousAction,
                  entry: InteractiveEntry) -> ConfirmationPermit:
        return self._safety.authorize_typed(action, entry)
    def reset(self,permit:ConfirmationPermit)->None:
        self._safety.consume(permit,DangerousAction.RESET); self.invalidate(); self._target.reset()
    def load(self,permit:ConfirmationPermit)->None:
        self._safety.consume(permit,DangerousAction.LOAD)
        if self._saved_state is None: raise InvalidSessionState("no saved state")
        self.invalidate(); self._target.load_state(self._saved_state)
    def close(self)->CloseReport:
        if self._state == SessionState.CLOSED: return CloseReport()
        report=self._breakpoint_manager.cleanup()
        self._target.close(); self._state=SessionState.CLOSED; self._snapshot=None
        return report


__all__=["Session"]
