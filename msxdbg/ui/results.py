"""Presentation-neutral command envelopes."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping, Optional, Protocol, Tuple
from msxdbg.debuginfo.diagnostics import Diagnostic
from msxdbg.debuginfo.model import Resolution
from msxdbg.debuginfo.index import SymbolMatch
from msxdbg.debuginfo.sources import SourceWindow
from msxdbg.session.breakpoints import BreakpointRecord
from msxdbg.session.frames import Frame
from msxdbg.session.results import DisassemblyResult, StopResult
from msxdbg.target.api import PageState, RegisterSet

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

@dataclass(frozen=True)
class FrameTable:
    frames: Tuple[Frame, ...]
    selected_index: int
    termination_reason: Optional[str] = None
    def __post_init__(self) -> None:
        object.__setattr__(self, "frames", tuple(self.frames))
        if not self.frames:
            raise ValueError("frame table requires at least one frame")
        if self.selected_index not in {frame.index for frame in self.frames}:
            raise ValueError("selected frame must be present in frame table")

@dataclass(frozen=True)
class StopPayload:
    result: StopResult

@dataclass(frozen=True)
class BreakpointPayload:
    record: Optional[BreakpointRecord]
    operation: str

@dataclass(frozen=True)
class BreakpointTable:
    records: Tuple[BreakpointRecord, ...]
    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))

@dataclass(frozen=True)
class RegisterTable:
    registers: RegisterSet

@dataclass(frozen=True)
class PageTable:
    pages: Tuple[PageState, ...]
    def __post_init__(self) -> None:
        object.__setattr__(self, "pages", tuple(self.pages))

@dataclass(frozen=True)
class SymbolPayload:
    resolution: Resolution[SymbolMatch]

@dataclass(frozen=True)
class SourcePayload:
    window: SourceWindow

@dataclass(frozen=True)
class DisassemblyPayload:
    result: DisassemblyResult

@dataclass(frozen=True)
class MessagePayload:
    message: str

@dataclass(frozen=True)
class HelpPayload:
    entries: Tuple[Tuple[str, str, str], ...]
    def __post_init__(self) -> None:
        object.__setattr__(self, "entries", tuple(self.entries))

@dataclass(frozen=True)
class UiAction:
    action: str
    CLEAR = "clear"
    QUIT = "quit"

__all__ = ["BreakpointPayload", "BreakpointTable", "CommandError",
           "CommandPayload", "CommandResult", "DisassemblyPayload", "FrameTable",
           "HelpPayload", "MessagePayload", "PageTable", "RegisterTable",
           "SourcePayload", "StopPayload", "SymbolPayload", "UiAction"]
