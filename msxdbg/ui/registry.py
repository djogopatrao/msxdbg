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
    def __init__(self) -> None:
        self._specifications = []
        self._lookup = {}

    def register(self, spec: CommandSpec) -> None:
        names = (spec.name,) + spec.aliases
        if any(not name or any(char.isspace() for char in name) for name in names):
            raise ValueError("command names must be non-empty words")
        duplicate = next((name for name in names if name in self._lookup), None)
        if duplicate is not None:
            raise ValueError(f"duplicate command or alias: {duplicate}")
        if len(set(names)) != len(names):
            raise ValueError("command aliases must be unique")
        self._specifications.append(spec)
        for name in names:
            self._lookup[name] = spec

    def lookup(self, name: str) -> CommandSpec:
        try:
            return self._lookup[name]
        except KeyError:
            raise KeyError(f"unknown command: {name}") from None

    def specifications(self) -> Tuple[CommandSpec, ...]:
        return tuple(self._specifications)

    def complete(self, request: CompletionRequest) -> Tuple[Completion, ...]:
        cursor = max(0, min(request.cursor, len(request.text)))
        before = request.text[:cursor]
        start = before.rfind(" ") + 1
        prefix = before[start:]
        if start == 0:
            names = sorted(self._lookup)
            return tuple(Completion(name, start, cursor) for name in names
                         if name.startswith(prefix))
        command = before.split(None, 1)[0]
        specification = self._lookup.get(command.split("/", 1)[0])
        if specification is None:
            return ()
        return specification.completer(CompletionRequest(request.text, cursor, request.catalog))

__all__ = ["CommandArguments", "CommandRegistry", "CommandSpec", "Completion", "CompletionRequest"]
