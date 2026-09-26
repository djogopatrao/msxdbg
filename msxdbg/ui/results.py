"""Presentation-neutral command envelopes."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Optional, Protocol, Tuple
from msxdbg.debuginfo.diagnostics import Diagnostic

class CommandPayload(Protocol): pass

@dataclass(frozen=True)
class CommandError:
    code: str
    message: str
    details: Mapping[str, object]

@dataclass(frozen=True)
class CommandResult:
    command: str
    ok: bool
    payload: Optional[CommandPayload] = None
    warnings: Tuple[Diagnostic, ...] = ()
    error: Optional[CommandError] = None
    def __post_init__(self) -> None:
        object.__setattr__(self, "warnings", tuple(self.warnings))
        if self.ok == (self.error is not None) or (not self.ok and self.payload is not None):
            raise ValueError("command result success and error fields disagree")

class UiAction: CLEAR = "clear"; QUIT = "quit"

__all__ = ["CommandError", "CommandPayload", "CommandResult", "UiAction"]
