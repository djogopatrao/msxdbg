"""Stack-frame analysis contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, Tuple

from msxdbg.debuginfo.model import Function, Resolution, Variable
from msxdbg.target.api import Instruction, RegisterSet
from .results import LocationResult
from .state import StopSnapshot


class FrameState(str, Enum):
    IX_ACTIVE = "ix-active"
    FRAMELESS = "frameless"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Frame:
    index: int
    pc: int
    scope_pc: int
    function: Resolution[Function]
    ix: Optional[int]
    state: FrameState


@dataclass(frozen=True)
class BacktraceResult:
    frames: Tuple[Frame, ...]
    termination_reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "frames", tuple(self.frames))


class FrameReader(Protocol):
    def read_memory(self, address: int, size: int) -> bytes: ...
    def disassemble(self, address: int, count: int) -> Tuple[Instruction, ...]: ...


class FrameService:
    def walk(self, snapshot: StopSnapshot, reader: FrameReader) -> BacktraceResult:
        raise NotImplementedError("FrameService.walk is not implemented")
    def frame_state(self, function: Function, pc: int, reader: FrameReader) -> FrameState:
        raise NotImplementedError("FrameService.frame_state is not implemented")
    def locate(self, variable: Variable, frame: Frame, registers: RegisterSet, reader: FrameReader) -> LocationResult:
        raise NotImplementedError("FrameService.locate is not implemented")


__all__ = ["BacktraceResult", "Frame", "FrameReader", "FrameService", "FrameState"]
