"""Parser for SDCC ``.lst`` artifacts.

The listing parser intentionally works on supplied text only. Linking an
artifact to an image, and consequently turning local offsets into addresses,
is the loader's responsibility.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

from .diagnostics import Diagnostic, Origin, ParseResult
from .model import Area, SourceSpan


_DIRECTIVE = re.compile(r"^\.(module|area|globl)\b\s*(.*?)\s*$", re.IGNORECASE)
_LABEL = re.compile(r"^((?:[A-Za-z_.$][\w.$]*|[0-9]+\$)):(?::)?\s*$")
_EQU = re.compile(r"^(?:\S+\s+)?(?:\.?equ\b|=)", re.IGNORECASE)
_SOURCE_COMMENT = re.compile(r";\s*(.+?):(\d+):\s?(.*)$")
_HEX_ADDRESS = re.compile(r"^[0-9A-Fa-f]{8}$")


@dataclass(frozen=True)
class ListingSymbol:
    """A local label or export declaration; exports have no known offset."""

    name: str
    area: str
    offset: Optional[int]
    origin: Origin


@dataclass(frozen=True)
class ListingLine:
    """One instruction and the C source line that preceded it, if any."""

    area: str
    offset: int
    source: Optional[SourceSpan]
    origin: Origin


@dataclass(frozen=True)
class ListingData:
    """Unrelocated records extracted from one listing artifact."""

    module_name: str
    areas: Tuple[Area, ...] = ()
    labels: Tuple[ListingSymbol, ...] = ()
    globals: Tuple[ListingSymbol, ...] = ()
    lines: Tuple[ListingLine, ...] = ()

    def __post_init__(self) -> None:
        for attribute in ("areas", "labels", "globals", "lines"):
            object.__setattr__(self, attribute, tuple(getattr(self, attribute)))

    def find_line(self, file_suffix: str, line: int) -> Optional[ListingLine]:
        """Find exact source line, else the next code line in the same file."""

        candidates = [
            item for item in self.lines
            if item.source is not None
            and item.source.normalized_path.endswith(file_suffix)
            and item.source.line is not None
            and item.source.line >= line
        ]
        return min(candidates, key=lambda item: item.source.line) if candidates else None


def _warning(code: str, message: str, origin: Path, line: int) -> Diagnostic:
    return Diagnostic(code, "warning", message, (Origin(origin, line, "lst"),))


def _module_name(value: str, fallback: Path) -> Optional[str]:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value or fallback.stem or None


def _address(raw: str) -> Optional[int]:
    """Return the fixed-column local offset, or ``None`` for a non-record."""

    if len(raw.rstrip("\r\n")) < 40:
        return None
    field = raw[:39][4:12]
    if not _HEX_ADDRESS.fullmatch(field):
        return None
    return int(field, 16)


def _source(raw: str) -> Optional[SourceSpan]:
    match = _SOURCE_COMMENT.search(raw)
    if match is None:
        return None
    path, line, text = match.groups()
    return SourceSpan(path, path.replace("\\", "/"), int(line), text or None)


def parse_lst(lines: Iterable[str] | None, origin: Path) -> ParseResult[ListingData]:
    """Parse a listing without I/O, preserving local offsets and raw names."""

    origin = Path(origin)
    diagnostics = []
    pending_source: Optional[SourceSpan] = None
    current_area = "_CODE"
    areas: dict[str, Area] = {}
    labels = []
    globals_ = []
    records: dict[tuple[str, int], ListingLine] = {}
    module: Optional[str] = origin.stem or None

    for number, raw in enumerate(lines or (), start=1):
        if not isinstance(raw, str):
            diagnostics.append(_warning("lst.invalid-line", "listing line is not text", origin, number))
            continue
        # The head includes the assembler line number, bytes and cycle count.
        # Never interpret relocation placeholders in it as assembly text.
        text = raw[40:].strip() if len(raw) >= 40 and raw[:4].isspace() else raw.strip()
        try:
            source = _source(text) if text.startswith(";") else None
        except ValueError:
            diagnostics.append(_warning("lst.invalid-source", "invalid C source location", origin, number))
            continue
        if source is not None:
            pending_source = source
            continue

        stripped = text.split(";", 1)[0].strip()
        directive = _DIRECTIVE.match(stripped)
        if directive is not None:
            kind, value = directive.groups()
            if kind.lower() == "module":
                parsed = _module_name(value, origin)
                if parsed is None:
                    diagnostics.append(_warning("lst.empty-module", "empty .module directive", origin, number))
                else:
                    module = parsed
            elif kind.lower() == "area":
                if not value:
                    diagnostics.append(_warning("lst.empty-area", "empty .area directive", origin, number))
                else:
                    current_area = value.split()[0]
                    areas.setdefault(current_area, Area(current_area, evidence=(Origin(origin, number, "lst-area"),)))
            else:
                name = value.split()[0] if value else ""
                if not name:
                    diagnostics.append(_warning("lst.empty-global", "empty .globl directive", origin, number))
                else:
                    globals_.append(ListingSymbol(name, current_area, None, Origin(origin, number, "lst-global")))
            continue

        offset = _address(raw)
        label = _LABEL.match(stripped)
        if offset is not None and offset > 0xFFFF:
            diagnostics.append(_warning("lst.offset-out-of-range", f"offset {offset:#x} exceeds 16-bit range", origin, number))
            continue
        if label is not None:
            if offset is None:
                diagnostics.append(_warning("lst.label-without-offset", f"label {label.group(1)!r} has no offset", origin, number))
            else:
                areas.setdefault(current_area, Area(current_area))
                labels.append(ListingSymbol(label.group(1), current_area, offset, Origin(origin, number, "lst-label")))
            continue

        if offset is None or not stripped or stripped.startswith(".") or _EQU.match(stripped):
            # EQU, directives and continuation rows consume no pending source.
            continue
        areas.setdefault(current_area, Area(current_area))
        key = (current_area, offset)
        if key in records:
            diagnostics.append(_warning("lst.duplicate-offset", f"duplicate offset {offset:#x} in {current_area}; first record retained", origin, number))
            pending_source = None
            continue
        records[key] = ListingLine(current_area, offset, pending_source, Origin(origin, number, "lst-instruction"))
        pending_source = None

    ordered_lines = tuple(sorted(records.values(), key=lambda item: (item.area, item.offset)))
    data = ListingData(module or "<unknown>", tuple(areas.values()), tuple(labels), tuple(globals_), ordered_lines)
    return ParseResult(data, tuple(diagnostics))


__all__ = ["ListingData", "ListingLine", "ListingSymbol", "parse_lst"]
