"""Contracts for parsing SDLD map files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Tuple

from .diagnostics import ParseResult
from .model import Symbol


@dataclass(frozen=True)
class MapData:
    """Public symbols collected from one map artifact."""

    symbols: Tuple[Symbol, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", tuple(self.symbols))


def parse_map(lines: Iterable[str], origin: Path) -> ParseResult[MapData]:
    """Parse an SDLD map artifact without performing I/O."""

    raise NotImplementedError("debuginfo.parse_map is not implemented")


__all__ = ["MapData", "parse_map"]
