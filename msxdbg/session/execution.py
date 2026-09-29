"""Execution-control contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol

from msxdbg.debuginfo.index import Project
from msxdbg.target.api import ExecutionStatus, Target
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
        hooks.invalidate()
        if request.kind == ExecutionKind.CONTINUE:
            self._target.continue_execution()
        elif request.kind == ExecutionKind.STEP:
            self._target.step_into()
        elif request.kind == ExecutionKind.NEXT:
            self._target.step_over()
        elif request.kind == ExecutionKind.STEPI:
            self._target.step_into()
        elif request.kind == ExecutionKind.FINISH:
            self._target.step_out()
        elif request.kind == ExecutionKind.UNTIL:
            if request.address is None:
                raise ValueError("until requires an address")
            self._target.run_to(request.address)
        else:
            raise ValueError(f"unsupported execution kind: {request.kind}")

        timeout = request.timeout_seconds
        deadline = None if timeout is None else self._clock.monotonic() + timeout
        while self._target.execution_status() != ExecutionStatus.STOPPED:
            if cancel.is_cancelled():
                self._target.interrupt()
            elif deadline is not None and self._clock.monotonic() >= deadline:
                self._target.interrupt()
            else:
                self._clock.sleep(0.05)
                continue
            if self._target.execution_status() != ExecutionStatus.STOPPED:
                raise TimeoutError("target did not confirm interruption")
        return hooks.capture_stop()


__all__ = ["CancellationToken", "Clock", "ExecutionController", "ExecutionHooks", "ExecutionKind", "ExecutionRequest"]
