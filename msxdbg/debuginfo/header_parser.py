"""Contracts for the restricted C-header type parser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, TYPE_CHECKING, Tuple

from .diagnostics import ParseResult
from .model import TypeDef

if TYPE_CHECKING:
    from .macros import MacroDefinition


@dataclass(frozen=True)
class HeaderInput:
    """Explicit header content and its physical path."""

    path: Path
    text: str


@dataclass(frozen=True)
class HeaderTypes:
    """Types and macro definitions accepted from the restricted grammar."""

    types: Tuple[TypeDef, ...] = ()
    macros: Tuple["MacroDefinition", ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "types", tuple(self.types))
        object.__setattr__(self, "macros", tuple(self.macros))


def parse_headers(inputs: Sequence[HeaderInput]) -> ParseResult[HeaderTypes]:
    """Parse explicitly supplied headers without importing the evaluator."""

    raise NotImplementedError("debuginfo.parse_headers is not implemented")


__all__ = ["HeaderInput", "HeaderTypes", "parse_headers"]
