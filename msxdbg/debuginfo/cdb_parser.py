"""Contracts for parsing SDCC CDB files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple

from .diagnostics import ParseResult
from .model import Function, SourceSpan, Symbol, TypeDef, Variable


@dataclass(frozen=True)
class CdbData:
    """Identity-preserving records extracted from CDB artifacts."""

    functions: Tuple[Function, ...] = ()
    symbols: Tuple[Variable, ...] = ()
    links: Tuple[str, ...] = ()
    lines: Tuple[SourceSpan, ...] = ()
    types: Tuple[TypeDef, ...] = ()

    def __post_init__(self) -> None:
        for attribute in ("functions", "symbols", "links", "lines", "types"):
            object.__setattr__(self, attribute, tuple(getattr(self, attribute)))


def parse_cdb(lines: Iterable[str], origin: Path) -> ParseResult[CdbData]:
    """Parse an SDCC CDB artifact without performing I/O."""

    raise NotImplementedError("debuginfo.parse_cdb is not implemented")


__all__ = ["CdbData", "parse_cdb"]
