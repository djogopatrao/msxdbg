"""Contracts for parsing SDCC listing files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple

from .diagnostics import ParseResult
from .model import Area, SourceSpan, Symbol


@dataclass(frozen=True)
class ListingData:
    """Unrelocated records extracted from one listing artifact."""

    module_name: str
    areas: Tuple[Area, ...] = ()
    labels: Tuple[Symbol, ...] = ()
    globals: Tuple[Symbol, ...] = ()
    lines: Tuple[SourceSpan, ...] = ()

    def __post_init__(self) -> None:
        for attribute in ("areas", "labels", "globals", "lines"):
            object.__setattr__(self, attribute, tuple(getattr(self, attribute)))


def parse_lst(lines: Iterable[str], origin: Path) -> ParseResult[ListingData]:
    """Parse an SDCC listing artifact without performing I/O."""

    raise NotImplementedError("debuginfo.parse_lst is not implemented")


__all__ = ["ListingData", "parse_lst"]
