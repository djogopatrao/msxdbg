"""Execution-control contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol

from msxdbg.debuginfo.index import Project
from msxdbg.target.api import Target
from .results import StopResult
from .state import StepMode


class ExecutionKind(str, Enum):
    CONTINUE = "continue"
    STEP = "step"
    NEXT = "next"
    STEPI = "stepi"
    FINISH = "finish"
    UNTIL = "until"


@dataclass(frozen=True)
class ExecutionRequest:
    kind: ExecutionKind
    address: Optional[int] = None
    mode: StepMode = StepMode.SOURCE
    timeout_seconds: Optional[float] = None


class Clock(Protocol):
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...


class CancellationToken(Protocol):
    def is_cancelled(self) -> bool: ...


class ExecutionHooks(Protocol):
    def invalidate(self) -> None: ...
    def capture_stop(self) -> StopResult: ...


class ExecutionController:
    def __init__(self, target: Target, project: Project, clock: Clock) -> None:
        self._target = target
        self._project = project
        self._clock = clock

    def run(self, request: ExecutionRequest, hooks: ExecutionHooks, cancel: CancellationToken) -> StopResult:
        raise NotImplementedError("ExecutionController.run is not implemented")


__all__ = ["CancellationToken", "Clock", "ExecutionController", "ExecutionHooks", "ExecutionKind", "ExecutionRequest"]
