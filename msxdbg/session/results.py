"""Domain results produced by session use cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING, Tuple

from msxdbg.debuginfo.model import CodeLocation, ImageId, Resolution
from msxdbg.target.api import Instruction

if TYPE_CHECKING:
    from .state import StopSnapshot


@dataclass(frozen=True)
class StopResult:
    snapshot: "StopSnapshot"
    matching_breakpoints: Tuple[int, ...] = ()
    reason: Optional[str] = None
    warnings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "matching_breakpoints", tuple(self.matching_breakpoints))
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True)
class ResolvedTarget:
    address: int
    location: Resolution[CodeLocation]
    description: str
    effective_line: Optional[int] = None


@dataclass(frozen=True)
class TargetQuery:
    address: Optional[int] = None
    symbol: Optional[str] = None
    path: Optional[str] = None
    line: Optional[int] = None
    image: Optional[ImageId] = None

    def __post_init__(self) -> None:
        kinds = (self.address is not None, self.symbol is not None, self.path is not None)
        if sum(kinds) != 1 or ((self.path is None) != (self.line is None)):
            raise ValueError("target query must select one complete query kind")


@dataclass(frozen=True)
class LocationResult:
    address: Optional[int] = None
    register_bytes: Optional[bytes] = None
    unavailable_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if sum(value is not None for value in (self.address, self.register_bytes, self.unavailable_reason)) != 1:
            raise ValueError("location result requires exactly one outcome")


@dataclass(frozen=True)
class DisassemblyResult:
    instructions: Tuple[Instruction, ...]
    annotations: Tuple[Resolution[CodeLocation], ...]
    pc: int
    next_cursor: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "instructions", tuple(self.instructions))
        object.__setattr__(self, "annotations", tuple(self.annotations))


@dataclass(frozen=True)
class MemoryWriteResult:
    address: int
    requested: bytes
    observed: bytes
    snapshot: "StopSnapshot"

    @property
    def verified(self) -> bool:
        return self.requested == self.observed


@dataclass(frozen=True)
class RegisterWriteResult:
    name: str
    requested: int
    observed: int
    snapshot: "StopSnapshot"


@dataclass(frozen=True)
class CloseReport:
    removed_ids: Tuple[str, ...] = ()
    pending_ids: Tuple[str, ...] = ()
    unknown_creations: Tuple[int, ...] = ()
    errors: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("removed_ids", "pending_ids", "unknown_creations", "errors"):
            object.__setattr__(self, name, tuple(getattr(self, name)))


class SessionError(Exception):
    pass


class InvalidSessionState(SessionError):
    pass


class TargetResolutionError(SessionError):
    pass


class SafetyError(SessionError):
    pass


class StaleInspectionError(SessionError):
    pass


class MutationVerificationError(SessionError):
    """A mutation was accepted but its resulting state could not be verified."""

    outcome_unknown = True

    def __init__(self, message: str, operation: str) -> None:
        super().__init__(message)
        self.operation = operation


__all__ = ["CloseReport", "DisassemblyResult", "InvalidSessionState", "LocationResult",
           "MemoryWriteResult", "MutationVerificationError", "RegisterWriteResult",
           "ResolvedTarget", "SafetyError",
           "SessionError", "StaleInspectionError", "StopResult", "TargetQuery",
           "TargetResolutionError"]
