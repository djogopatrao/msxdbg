"""Parse SDCC CDB records without I/O or image-dependent reconciliation.

Declarations deliberately are not linked model.Function/model.Variable objects.
All identity links survive for the loader to match across artifacts; an absent
exit marker stays absent, and neither function bounds nor addresses are guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Tuple

from .diagnostics import Diagnostic, Origin, ParseResult
from .model import SourceSpan


_LEVEL = re.compile(r"([0-9]+)(?:_([0-9]+))?")
_DECLARATION = re.compile(r"([^()]+)\(\{([0-9]+)\}([^()]+)\),(.*)")
_STORAGE = re.compile(r"([A-Z]),([01]),(-?[0-9]+)(?:,\[([^\[\]]*)\](?:,([A-Z]),([01]),(-?[0-9]+))?)?")
_TYPE = re.compile(r"F([^$\[\]]+)\$([^$\[\]]+)\[(.*)\]")
_MEMBER = re.compile(r"\(\{([0-9]+)\}S:([^()]+\([^()]+\),[^()]*)\)")
_MEMBER_TYPE_TOKEN = re.compile(r"(?:D[GCXDPIF]|DA[0-9]+d?|S[LICSVF]|ST[^,:()]+)")
_HEX = re.compile(r"[0-9a-fA-F]+")


@dataclass(frozen=True)
class CdbIdentity:
    """Full identity; absent sublevel is distinct from an explicit zero."""

    raw: str
    scope: str
    name: str
    level: int
    sublevel: Optional[int]
    block: int

    @property
    def module_key(self) -> Optional[str]:
        if self.scope.startswith("F"):
            return self.scope[1:]
        if self.scope.startswith("L") and "." in self.scope:
            return self.scope[1:].rsplit(".", 1)[0]
        return None

    @property
    def function_name(self) -> Optional[str]:
        if self.scope.startswith("L"):
            return self.scope[1:].rsplit(".", 1)[-1]
        return None


@dataclass(frozen=True)
class CdbTypeChain:
    """Encoded type, not a resolved TypeDef graph or an inferred layout."""

    size: int
    raw: str
    signed: bool


@dataclass(frozen=True)
class CdbStorage:
    """Encoded allocation, preserving registers and optional spill location.

    Offset is canonical CDB stack displacement, never a CPU address. Fixed
    storage still needs an L record; zero in its tail is not address zero.
    """

    code: str
    on_stack: bool
    offset: int
    registers: Tuple[str, ...] = ()
    fallback: Optional[CdbStorage] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "registers", tuple(self.registers))


@dataclass(frozen=True)
class CdbSymbol:
    identity: CdbIdentity
    type_chain: CdbTypeChain
    storage: CdbStorage
    origin: Origin

    @property
    def is_temporary(self) -> bool:
        """Allocator temporaries must be filtered from user-visible locals."""
        return re.fullmatch(r"sloc[0-9]+", self.identity.name) is not None


@dataclass(frozen=True)
class CdbFunction:
    identity: CdbIdentity
    type_chain: CdbTypeChain
    storage: CdbStorage
    is_interrupt: bool
    interrupt_number: int
    register_bank: int
    origin: Origin


@dataclass(frozen=True)
class CdbModule:
    name: str
    origin: Origin


@dataclass(frozen=True)
class CdbLink:
    """Unclassified symbol link, including the original X exit prefix.

    Matching against F/S declarations belongs to the loader. An X address is
    retained inclusive; only a proven function match may become a function end.
    """

    identity: str
    address: int
    origin: Origin


@dataclass(frozen=True)
class CdbLine:
    identity: str
    source: SourceSpan
    address: int
    level: int
    sublevel: Optional[int]
    block: int
    origin: Origin


@dataclass(frozen=True)
class CdbField:
    offset: int
    symbol: CdbSymbol


@dataclass(frozen=True)
class CdbType:
    """Encoded members only; size, union/struct layout and graph are unresolved."""

    identity: str
    module_key: str
    name: str
    fields: Tuple[CdbField, ...]
    origin: Origin

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))


@dataclass(frozen=True)
class CdbData:
    """Immutable, identity-preserving records from one artifact, in file order."""

    functions: Tuple[CdbFunction, ...] = ()
    symbols: Tuple[CdbSymbol, ...] = ()
    links: Tuple[CdbLink, ...] = ()
    lines: Tuple[CdbLine, ...] = ()
    types: Tuple[CdbType, ...] = ()
    modules: Tuple[CdbModule, ...] = ()

    def __post_init__(self) -> None:
        for attribute in ("functions", "symbols", "links", "lines", "types", "modules"):
            object.__setattr__(self, attribute, tuple(getattr(self, attribute)))


class _InvalidRecord(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _level(raw: str) -> tuple[int, Optional[int]]:
    match = _LEVEL.fullmatch(raw)
    if match is None:
        raise ValueError("invalid lexical level/sublevel")
    return int(match[1]), int(match[2]) if match[2] is not None else None


def _identity(raw: str, *, member: bool = False) -> CdbIdentity:
    parts = raw.split("$")
    if len(parts) != 4:
        raise ValueError("identity must preserve scope, name, level and block")
    scope, name, level_text, block = parts
    valid_scope = scope == "G" or (scope.startswith(("F", "L")) and len(scope) > 1)
    if member:
        valid_scope = scope == "S"
    if not valid_scope or not name or not re.fullmatch(r"[0-9]+", block):
        raise ValueError("invalid identity scope, name or block")
    level, sublevel = _level(level_text)
    return CdbIdentity(raw, scope, name, level, sublevel, int(block))


def _storage(raw: str) -> CdbStorage:
    match = _STORAGE.fullmatch(raw)
    if match is None:
        raise ValueError("invalid allocation tail")
    code, on_stack, offset, regs, fallback_code, fallback_stack, fallback_offset = match.groups()
    if (code == "R") != (regs is not None):
        raise ValueError("register allocation must contain a register list")
    registers = tuple(x.strip() for x in regs.split(",")) if regs is not None else ()
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_']*", x) for x in registers):
        raise ValueError("invalid or empty register name")
    known_codes = "ABCDEFGHIJRZ"
    if code not in known_codes or fallback_code is not None and fallback_code not in known_codes:
        raise _InvalidRecord("cdb.unsupported-storage", "unsupported address-space code")
    fallback = None
    if fallback_code is not None:
        if fallback_code == "R":
            raise ValueError("register fallback has no register list")
        fallback = CdbStorage(fallback_code, fallback_stack == "1", int(fallback_offset))
    return CdbStorage(code, on_stack == "1", int(offset), registers, fallback)


def _declaration(payload: str, origin: Origin, *, function: bool = False,
                 member: bool = False) -> CdbSymbol | CdbFunction:
    match = _DECLARATION.fullmatch(payload)
    if match is None:
        raise ValueError("invalid declaration or truncated type chain")
    raw_identity, size, chain, tail = match.groups()
    identity = _identity(raw_identity, member=member)
    tokens, separator, sign = chain.rpartition(":")
    if not separator or sign not in ("S", "U") or not tokens or any(not x for x in tokens.split(",")):
        raise ValueError("type chain requires tokens and S/U signedness")
    if member and any(_MEMBER_TYPE_TOKEN.fullmatch(x) is None for x in tokens.split(",")):
        raise _InvalidRecord("cdb.unsupported-type", "unsupported T member type chain")
    type_chain = CdbTypeChain(int(size), chain, sign == "S")
    if not function:
        return CdbSymbol(identity, type_chain, _storage(tail), origin)
    parts = tail.rsplit(",", 3)
    if len(parts) != 4 or parts[1] not in ("0", "1") or any(
        re.fullmatch(r"[0-9]+", x) is None for x in parts[2:]
    ):
        raise ValueError("invalid function interrupt/bank tail")
    return CdbFunction(identity, type_chain, _storage(parts[0]), parts[1] == "1",
                       int(parts[2]), int(parts[3]), origin)


def _type(payload: str, origin: Origin) -> CdbType:
    match = _TYPE.fullmatch(payload)
    if match is None:
        raise _InvalidRecord("cdb.unsupported-type", "unsupported or truncated T record")
    module, name, body = match.groups()
    fields = []
    position = 0
    while position < len(body):
        field = _MEMBER.match(body, position)
        if field is None:
            raise _InvalidRecord("cdb.unsupported-type", "unsupported T member encoding")
        symbol = _declaration(field[2], origin, member=True)
        fields.append(CdbField(int(field[1]), symbol))
        position = field.end()
    return CdbType(f"F{module}${name}", module, name, tuple(fields), origin)


def _link(payload: str, origin: Origin) -> CdbLink | CdbLine | None:
    # ASM line records have no offline C-source role, even if irrelevant/truncated.
    if payload.startswith("A$"):
        return None
    identity, colon, raw_address = payload.rpartition(":")
    if not colon or not _HEX.fullmatch(raw_address):
        raise ValueError("invalid link address")
    address = int(raw_address, 16)
    if address > 0xFFFF:
        raise _InvalidRecord("cdb.address-out-of-range", "link address exceeds 16-bit space")
    if identity.startswith("C$"):
        parts = identity[2:].rsplit("$", 3)
        if len(parts) != 4:
            raise ValueError("invalid C-line identity")
        path, raw_line, raw_level, raw_block = parts
        if not re.fullmatch(r"[0-9]+", raw_line) or not re.fullmatch(r"[0-9]+", raw_block):
            raise ValueError("invalid C-line number or block")
        level, sublevel = _level(raw_level)
        source = SourceSpan(path, path.replace("\\", "/"), int(raw_line))
        return CdbLine(identity, source, address, level, sublevel, int(raw_block), origin)
    _identity(identity[1:] if identity.startswith("X") else identity)
    return CdbLink(identity, address, origin)


def parse_cdb(lines: Iterable[str] | None, origin: Path) -> ParseResult[CdbData]:
    """Collect M/F/S/L/T records; malformed rows do not erase valid records.

    Keep duplicates and their origins for later reconciliation. M records are
    metadata, not implicit scope switches. In particular, a G identity is not
    attributed to whichever M happened to occur most recently.
    """
    path = Path(origin)
    functions, symbols, links, source_lines, types, modules, diagnostics = [], [], [], [], [], [], []
    for number, raw in enumerate(lines or (), start=1):
        evidence = Origin(path, number, "cdb")
        try:
            if not isinstance(raw, str):
                raise ValueError("record is not text")
            raw = raw.strip()
            if not raw or raw.startswith((";", "#")):
                continue
            kind, colon, payload = raw.partition(":")
            if not colon or kind not in ("M", "F", "S", "L", "T"):
                raise _InvalidRecord("cdb.unsupported-record", "unsupported record kind")
            evidence = Origin(path, number, f"cdb-{kind}")
            if kind == "M":
                if not payload or any(x.isspace() for x in payload):
                    raise ValueError("invalid module name")
                modules.append(CdbModule(payload, evidence))
            elif kind == "F":
                functions.append(_declaration(payload, evidence, function=True))
            elif kind == "S":
                symbols.append(_declaration(payload, evidence))
            elif kind == "T":
                types.append(_type(payload, evidence))
            else:
                link = _link(payload, evidence)
                if isinstance(link, CdbLine):
                    source_lines.append(link)
                elif link is not None:
                    links.append(link)
        except ValueError as exc:
            code = exc.code if isinstance(exc, _InvalidRecord) else "cdb.invalid-record"
            diagnostics.append(Diagnostic(code, "warning", str(exc), (evidence,)))
    return ParseResult(CdbData(tuple(functions), tuple(symbols), tuple(links),
                               tuple(source_lines), tuple(types), tuple(modules)), tuple(diagnostics))


__all__ = ["CdbData", "CdbIdentity", "CdbTypeChain", "CdbStorage", "CdbSymbol",
           "CdbFunction", "CdbModule", "CdbLink", "CdbLine", "CdbField", "CdbType", "parse_cdb"]
