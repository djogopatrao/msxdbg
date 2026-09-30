"""Typed target protocol and data transferred across the target boundary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping, NoReturn, Optional, Protocol, Tuple


class ExecutionStatus(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"


@dataclass(frozen=True)
class RegisterSet:
    values: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    def get(self, name: str) -> int:
        key = name.upper()
        aliases = {"AF2": "AF'", "BC2": "BC'", "DE2": "DE'", "HL2": "HL'"}
        key = aliases.get(key, key)
        if key in self.values:
            return self.values[key]
        pairs = {"AF": ("A", "F"), "BC": ("B", "C"), "DE": ("D", "E"),
                 "HL": ("H", "L"), "IX": ("IXH", "IXL"), "IY": ("IYH", "IYL"),
                 "PC": ("PCH", "PCL"), "SP": ("SPH", "SPL"),
                 "AF'": ("A2", "F2"), "BC'": ("B2", "C2"),
                 "DE'": ("D2", "E2"), "HL'": ("H2", "L2")}
        if key in pairs and all(part in self.values for part in pairs[key]):
            high, low = pairs[key]
            return (self.values[high] << 8) | self.values[low]
        for pair, (high, low) in pairs.items():
            if key == high and pair in self.values:
                return (self.values[pair] >> 8) & 0xFF
            if key == low and pair in self.values:
                return self.values[pair] & 0xFF
        raise KeyError(name)

    def width(self, name: str) -> int:
        key = name.upper()
        self.get(key)
        return 16 if key in {"AF", "BC", "DE", "HL", "IX", "IY", "SP", "PC",
                             "AF'", "BC'", "DE'", "HL'", "AF2", "BC2", "DE2", "HL2"} else 8


@dataclass(frozen=True)
class Instruction:
    address: int
    size: int
    text: str
    raw_bytes: bytes

    def __post_init__(self) -> None:
        if not 0 <= self.address <= 0xFFFF:
            raise ValueError("instruction address must be a CPU address")
        if self.size < 1 or len(self.raw_bytes) != self.size:
            raise ValueError("instruction size must match raw bytes")


@dataclass(frozen=True)
class PageState:
    page: int
    primary_slot: str
    secondary_slot: str
    segment: str

    def __post_init__(self) -> None:
        if self.page not in (0, 1, 2, 3):
            raise ValueError("page must be between 0 and 3")


@dataclass(frozen=True)
class RemoteBreakpoint:
    id: str
    address: int

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("remote breakpoint id must not be empty")
        if not 0 <= self.address <= 0xFFFF:
            raise ValueError("breakpoint address must be a CPU address")


@dataclass(frozen=True)
class RemoteWatchpoint:
    id: str
    access: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if not self.id or self.access not in ("read", "write"):
            raise ValueError("invalid remote watchpoint")
        if not 0 <= self.start <= self.end <= 0xFFFF:
            raise ValueError("invalid watchpoint range")


@dataclass(frozen=True)
class TargetCapabilities:
    persistent: bool = False
    block_read: bool = False
    conditional_breakpoints: Optional[bool] = None
    watchpoints: Optional[bool] = None
    mapping_conditions: Optional[bool] = None
    memory_write: Optional[bool] = None
    register_write: Optional[bool] = None


class TargetError(Exception):
    """Base error carrying operation and mutation-outcome certainty."""

    def __init__(
        self, message: str, operation: str, outcome_unknown: bool = False
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.outcome_unknown = outcome_unknown


class TargetUnavailable(TargetError):
    pass


class TargetTimeout(TargetError):
    pass


class TargetCommandError(TargetError):
    pass


class TargetProtocolError(TargetError):
    pass


class Target(Protocol):
    def execution_status(self) -> ExecutionStatus: ...

    def read_registers(self) -> RegisterSet: ...

    def read_memory(self, address: int, size: int) -> bytes: ...

    def write_memory(self, address: int, data: bytes) -> None: ...

    def write_register(self, name: str, value: int) -> None: ...

    def disassemble(self, address: int, count: int) -> Tuple[Instruction, ...]: ...

    def read_pages(self) -> Tuple[PageState, ...]: ...

    def continue_execution(self) -> None: ...

    def step_into(self) -> None: ...

    def step_over(self) -> None: ...

    def step_out(self) -> None: ...

    def run_to(self, address: int) -> None: ...

    def interrupt(self) -> None: ...

    def create_breakpoint(self, address: int, condition: str = "") -> str: ...

    def remove_breakpoint(self, remote_id: str) -> None: ...

    def list_breakpoints(self) -> Tuple[RemoteBreakpoint, ...]: ...

    def create_watchpoint(self, access: str, start: int, end: int,
                          condition: str = "") -> str: ...

    def remove_watchpoint(self, remote_id: str) -> None: ...

    def list_watchpoints(self) -> Tuple[RemoteWatchpoint, ...]: ...

    def reset(self) -> None: ...

    def save_state(self, name: str) -> None: ...

    def load_state(self, name: str) -> None: ...

    def close(self) -> None: ...


class _UnimplementedTarget:
    """Shared explicit failures for concrete target stubs."""

    def _missing(self, operation: str) -> NoReturn:
        raise NotImplementedError(f"target operation {operation} is not implemented")

    def execution_status(self) -> ExecutionStatus:
        self._missing("execution_status")

    def read_registers(self) -> RegisterSet:
        self._missing("read_registers")

    def read_memory(self, address: int, size: int) -> bytes:
        self._missing("read_memory")

    def write_memory(self, address: int, data: bytes) -> None:
        self._missing("write_memory")

    def write_register(self, name: str, value: int) -> None:
        self._missing("write_register")

    def disassemble(self, address: int, count: int) -> Tuple[Instruction, ...]:
        self._missing("disassemble")

    def read_pages(self) -> Tuple[PageState, ...]:
        self._missing("read_pages")

    def continue_execution(self) -> None:
        self._missing("continue_execution")

    def step_into(self) -> None:
        self._missing("step_into")

    def step_over(self) -> None:
        self._missing("step_over")

    def step_out(self) -> None:
        self._missing("step_out")

    def run_to(self, address: int) -> None:
        self._missing("run_to")

    def interrupt(self) -> None:
        self._missing("interrupt")

    def create_breakpoint(self, address: int, condition: str = "") -> str:
        self._missing("create_breakpoint")

    def remove_breakpoint(self, remote_id: str) -> None:
        self._missing("remove_breakpoint")

    def list_breakpoints(self) -> Tuple[RemoteBreakpoint, ...]:
        self._missing("list_breakpoints")

    def create_watchpoint(self, access: str, start: int, end: int,
                          condition: str = "") -> str:
        self._missing("create_watchpoint")

    def remove_watchpoint(self, remote_id: str) -> None:
        self._missing("remove_watchpoint")

    def list_watchpoints(self) -> Tuple[RemoteWatchpoint, ...]:
        self._missing("list_watchpoints")

    def reset(self) -> None:
        self._missing("reset")

    def save_state(self, name: str) -> None:
        self._missing("save_state")

    def load_state(self, name: str) -> None:
        self._missing("load_state")

    def close(self) -> None:
        self._missing("close")


__all__ = [
    "ExecutionStatus", "Instruction", "PageState", "RegisterSet",
    "RemoteBreakpoint", "RemoteWatchpoint", "Target", "TargetCapabilities", "TargetCommandError",
    "TargetError", "TargetProtocolError", "TargetTimeout", "TargetUnavailable",
]
