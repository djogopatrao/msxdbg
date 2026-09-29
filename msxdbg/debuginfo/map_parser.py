"""Parser for the public-symbol table of SDLD/ASxxxx ``.map`` files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

from .diagnostics import Diagnostic, Origin, ParseResult


_TABLE_HEADER = re.compile(
    r"^\s*Value\s+Global(?:\s+Global\s+Defined\s+In\s+Module)?\s*$",
    re.IGNORECASE,
)
_PAGE_HEADER = re.compile(r"^\s*ASxxxx\s+Linker\b", re.IGNORECASE)
_SYMBOL_ROW = re.compile(r"^\s*([0-9A-Fa-f]{4,8})\s+(\S+)(?:\s+(\S+))?\s*$")
_TABLE_SEPARATOR = re.compile(r"^\s*-+(?:\s+-+)*\s*$")


@dataclass(frozen=True)
class MapSymbol:
    """A raw MAP row; ``module_key`` becomes a ``ModuleId`` only in the loader."""

    name: str
    address: int
    module_key: Optional[str]
    origin: Origin

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("map symbol name must not be empty")
        if not 0 <= self.address <= 0xFFFF:
            raise ValueError("map symbol address must be a CPU address")


@dataclass(frozen=True)
class MapData:
    """Public symbols collected from one MAP artifact."""

    symbols: Tuple[MapSymbol, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbols", tuple(self.symbols))


def _diagnostic(code: str, message: str, path: Path, line: int) -> Diagnostic:
    return Diagnostic(code, "warning", message, (Origin(path, line, "map"),))


def _parse_row(raw_line: str, path: Path, line_number: int) -> MapSymbol | Diagnostic | None:
    stripped = raw_line.strip()
    if not stripped or _TABLE_SEPARATOR.match(raw_line):
        return None

    match = _SYMBOL_ROW.match(raw_line)
    if match is None:
        return _diagnostic("map.invalid-row", f"invalid Value Global row: {stripped!r}", path, line_number)

    address = int(match.group(1), 16)
    if address > 0xFFFF:
        return _diagnostic("map.address-out-of-range", f"address {address:#x} exceeds the Z80 address space", path, line_number)

    name = match.group(2)
    module_key = match.group(3)
    if name.startswith(("s__", "l__")):
        module_key = None
    return MapSymbol(name, address, module_key, Origin(path, line_number, "map"))


def parse_map(lines: Iterable[str], origin: Path) -> ParseResult[MapData]:
    """Parse rows inside ``Value Global`` tables without performing I/O."""

    symbols = []
    diagnostics = []
    in_value_global = False
    for line_number, raw_line in enumerate(lines or (), start=1):
        if _TABLE_HEADER.match(raw_line):
            in_value_global = True
            continue
        if _PAGE_HEADER.match(raw_line):
            in_value_global = False
            continue
        if not in_value_global:
            continue
        parsed = _parse_row(raw_line, origin, line_number)
        if isinstance(parsed, Diagnostic):
            diagnostics.append(parsed)
        elif parsed is not None:
            symbols.append(parsed)
    return ParseResult(MapData(tuple(symbols)), tuple(diagnostics))


__all__ = ["MapData", "MapSymbol", "parse_map"]
