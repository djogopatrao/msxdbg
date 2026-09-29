"""Session state, snapshots, configuration, and inspection protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Protocol, TYPE_CHECKING, Tuple

from msxdbg.debuginfo.index import SymbolContext
from msxdbg.debuginfo.model import CodeLocation, FunctionId, Resolution, Variable
from msxdbg.target.api import RegisterSet

if TYPE_CHECKING:
    from .frames import Frame
    from .results import LocationResult


class SessionState(str, Enum):
    DISCONNECTED = "disconnected"
    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"
    CLOSED = "closed"


class StepMode(str, Enum):
    SOURCE = "source"
    ASSEMBLY = "assembly"


@dataclass(frozen=True)
class SignatureSpec:
    address: int
    expected: bytes

    def __post_init__(self) -> None:
        if not self.expected or not 0 <= self.address <= 0xFFFF:
            raise ValueError("signature requires bytes at a CPU address")
        if self.address + len(self.expected) > 0x10000:
            raise ValueError("signature must not wrap memory")


@dataclass(frozen=True)
class SessionConfig:
    signature: Optional[SignatureSpec] = None
    initial_mode: StepMode = StepMode.SOURCE
    polling_interval: float = 0.05
    step_limit: int = 20000
    frame_limit: int = 64
    execution_timeout: Optional[float] = None


@dataclass(frozen=True)
class StopSnapshot:
    stop_id: int
    memory_epoch: int
    registers: RegisterSet
    pc_resolution: Resolution[CodeLocation]
    signature_status: str
    known_reason: Optional[str] = None


@dataclass
class SelectionState:
    stop_id: int
    frame_index: int = 0


@dataclass
class StopCache:
    memory: Dict[Tuple[int, int], bytes] = field(default_factory=dict)
    frames: Tuple["Frame", ...] = ()
    frame_termination_reason: Optional[str] = None
    function_states: Dict[FunctionId, object] = field(default_factory=dict)


class InspectionContext(Protocol):
    @property
    def stop_id(self) -> int: ...
    @property
    def frame(self) -> "Frame": ...
    @property
    def registers(self) -> RegisterSet: ...
    @property
    def symbol_context(self) -> SymbolContext: ...
    def read_memory(self, address: int, size: int) -> bytes: ...
    def locate_variable(self, variable: Variable) -> "LocationResult": ...
    def validate(self) -> None: ...


__all__ = ["InspectionContext", "SelectionState", "SessionConfig", "SessionState", "SignatureSpec", "StepMode", "StopCache", "StopSnapshot"]
