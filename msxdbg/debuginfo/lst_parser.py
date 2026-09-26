"""LST file parser stub."""


from __future__ import annotations
from typing import Iterable, List, Dict
from pathlib import Path

Record = dict  # type: ignore[misc]


def parse_lst(lines: Iterable[str], origin: Path) -> Record:
    """Parse .lst file stub. Returns empty record."""
    return {}


__all__ = ['parse_lst']
