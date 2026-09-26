"""Public session facade contract."""

from __future__ import annotations

from typing import Tuple

from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import Resolution
from msxdbg.target.api import PageState, Target
from .breakpoints import BreakpointRecord
from .execution import CancellationToken, Clock, ExecutionRequest
from .frames import BacktraceResult, Frame
from .memory_map import MemoryLayoutPolicy, Page3Report
from .results import CloseReport, DisassemblyResult, ResolvedTarget, StopResult, TargetQuery
from .safety import ConfirmationPermit, SafetyGate
from .state import InspectionContext, SessionConfig, SessionState, StepMode


class Session:
    def __init__(self, project: Project, target: Target, config: SessionConfig, safety: SafetyGate, clock: Clock) -> None:
        self._project = project
        self._target = target
        self._config = config
        self._safety = safety
        self._clock = clock

    def _missing(self, name: str):
        raise NotImplementedError(f"Session.{name} is not implemented")
    def attach(self) -> SessionState: return self._missing("attach")
    def reconcile(self) -> SessionState: return self._missing("reconcile")
    def resolve_target(self, query: TargetQuery) -> Resolution[ResolvedTarget]: return self._missing("resolve_target")
    def execute(self, request: ExecutionRequest, cancel: CancellationToken) -> StopResult: return self._missing("execute")
    def where(self) -> StopResult: return self._missing("where")
    def inspection(self) -> InspectionContext: return self._missing("inspection")
    def backtrace(self) -> BacktraceResult: return self._missing("backtrace")
    def select_frame(self, index: int) -> Frame: return self._missing("select_frame")
    def add_breakpoint(self, target: ResolvedTarget) -> BreakpointRecord: return self._missing("add_breakpoint")
    def delete_breakpoint(self, number: int) -> None: self._missing("delete_breakpoint")
    def suspend_breakpoint(self, number: int) -> BreakpointRecord: return self._missing("suspend_breakpoint")
    def resume_breakpoint(self, number: int) -> BreakpointRecord: return self._missing("resume_breakpoint")
    def breakpoints(self) -> Tuple[BreakpointRecord, ...]: return self._missing("breakpoints")
    def disassemble(self, address: int, count: int) -> DisassemblyResult: return self._missing("disassemble")
    def pages(self) -> Tuple[PageState, ...]: return self._missing("pages")
    def page3(self, policy: MemoryLayoutPolicy) -> Page3Report: return self._missing("page3")
    def set_mode(self, mode: StepMode) -> None: self._missing("set_mode")
    def save(self) -> None: self._missing("save")
    def reset(self, permit: ConfirmationPermit) -> None: self._missing("reset")
    def load(self, permit: ConfirmationPermit) -> None: self._missing("load")
    def close(self) -> CloseReport: return self._missing("close")


__all__ = ["Session"]
