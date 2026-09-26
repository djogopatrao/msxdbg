"""Offline macro-definition contracts used before expression parsing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .diagnostics import Origin, ParseResult
from .model import ImageId, Resolution


@dataclass(frozen=True)
class MacroToken:
    """Lexical replacement token independent of the evaluator."""

    lexeme: str


@dataclass(frozen=True)
class MacroContext:
    """Known image and translation-unit preprocessing context."""

    image: Optional[ImageId] = None
    translation_unit: Optional[str] = None


@dataclass(frozen=True)
class MacroDefinition:
    """Object-like or function-like macro with its source provenance."""

    name: str
    parameters: Optional[Tuple[str, ...]]
    replacement: Tuple[MacroToken, ...]
    origin: Origin
    context: MacroContext

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("macro name must not be empty")
        if self.parameters is not None:
            object.__setattr__(self, "parameters", tuple(self.parameters))
        object.__setattr__(self, "replacement", tuple(self.replacement))


@dataclass(frozen=True)
class MacroCatalog:
    """Immutable collection that preserves conflicting definitions."""

    definitions: Tuple[MacroDefinition, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "definitions", tuple(self.definitions))

    def lookup(
        self,
        name: str,
        context: MacroContext,
    ) -> Resolution[MacroDefinition]:
        """Resolve a macro without collapsing ambiguous definitions."""

        raise NotImplementedError("MacroCatalog.lookup is not implemented")

    def names(self, context: MacroContext) -> Tuple[str, ...]:
        """Return macro names visible in a known context."""

        raise NotImplementedError("MacroCatalog.names is not implemented")


def parse_macro_definitions(
    text: str,
    origin: Path,
    context: MacroContext,
) -> ParseResult[Tuple[MacroDefinition, ...]]:
    """Parse supported definitions without invoking a preprocessor."""

    raise NotImplementedError("debuginfo.parse_macro_definitions is not implemented")


__all__ = [
    "MacroCatalog",
    "MacroContext",
    "MacroDefinition",
    "MacroToken",
    "parse_macro_definitions",
]
