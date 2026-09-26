"""Command metadata and lookup contracts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Optional, Protocol, Tuple
from msxdbg.debuginfo.index import CompletionCatalog
from msxdbg.session.safety import DangerousAction
from .results import CommandResult

class CommandArguments(Protocol): pass

@dataclass(frozen=True)
class CompletionRequest:
    text: str; cursor: int; catalog: CompletionCatalog
@dataclass(frozen=True)
class Completion:
    value: str; start: int; end: int

@dataclass(frozen=True)
class CommandSpec:
    name: str
    aliases: Tuple[str, ...]
    help_text: str
    syntax: str
    repeatable: bool
    confirmation: Optional[DangerousAction]
    parser: Callable[[str], CommandArguments]
    handler: Callable[[CommandArguments, object], CommandResult]
    completer: Callable[[CompletionRequest], Tuple[Completion, ...]]
    def __post_init__(self) -> None: object.__setattr__(self, "aliases", tuple(self.aliases))

class CommandRegistry:
    def register(self, spec: CommandSpec) -> None: raise NotImplementedError("CommandRegistry.register is not implemented")
    def lookup(self, name: str) -> CommandSpec: raise NotImplementedError("CommandRegistry.lookup is not implemented")
    def specifications(self) -> Tuple[CommandSpec, ...]: raise NotImplementedError("CommandRegistry.specifications is not implemented")
    def complete(self, request: CompletionRequest) -> Tuple[Completion, ...]: raise NotImplementedError("CommandRegistry.complete is not implemented")

__all__ = ["CommandArguments", "CommandRegistry", "CommandSpec", "Completion", "CompletionRequest"]
