"""Map file parser stub."""


from __future__ import annotations
from typing import Iterable, TypeVar, Dict
from pathlib import Path

T = TypeVar('T')
MapData = Dict[str, T]  # type: ignore[misc]


def parse_map(lines: Iterable[str], origin: Path) -> MapData:
    """Parse .map file stub. Returns empty dict when no files present."""
    return {}

__all__ = ['parse_map']
