"""Immutable offline model for parsed and reconciled debug information."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Optional, Tuple, TypeVar, Union

from .diagnostics import Diagnostic, Origin


T = TypeVar("T")


@dataclass(frozen=True, order=True)
class ImageId:
    """Stable textual identity of a linked image."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("image id must not be empty")


@dataclass(frozen=True, order=True)
class ModuleId:
    """Identity of a module within an image."""

    image: ImageId
    key: str

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("module key must not be empty")


@dataclass(frozen=True, order=True)
class FunctionId:
    """Identity of a function record within a module."""

    module: ModuleId
    record_identity: str

    def __post_init__(self) -> None:
        if not self.record_identity:
            raise ValueError("function record identity must not be empty")


@dataclass(frozen=True, order=True)
class VariableId:
    """Complete scoped identity of a variable record."""

    module: ModuleId
    record_identity: str

    def __post_init__(self) -> None:
        if not self.record_identity:
            raise ValueError("variable record identity must not be empty")


@dataclass(frozen=True, order=True)
class TypeId:
    """Identity of a primitive or image/module-specific type."""

    record_identity: str
    image: Optional[ImageId] = None
    module: Optional[ModuleId] = None

    def __post_init__(self) -> None:
        if not self.record_identity:
            raise ValueError("type record identity must not be empty")
        if self.module is not None and self.image not in (None, self.module.image):
            raise ValueError("type image and module image must agree")


@dataclass(frozen=True)
class AddressRange:
    """Half-open CPU address interval ``[start, end_exclusive)``."""

    start: int
    end_exclusive: int

    def __post_init__(self) -> None:
        if not 0 <= self.start <= 0xFFFF:
            raise ValueError("range start must be a CPU address")
        if not 1 <= self.end_exclusive <= 0x10000:
            raise ValueError("range end must be between 1 and 65536")
        if self.start >= self.end_exclusive:
            raise ValueError("address range must not be empty or inverted")

    def contains(self, address: int) -> bool:
        """Return whether *address* lies inside this non-wrapping interval."""

        return self.start <= address < self.end_exclusive


@dataclass(frozen=True)
class SourceSpan:
    """Source location with its original and normalized paths."""

    path: str
    normalized_path: str
    line: Optional[int] = None
    text: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.path or not self.normalized_path:
            raise ValueError("source paths must not be empty")
        if self.line is not None and self.line < 1:
            raise ValueError("source line must be positive")


@dataclass(frozen=True)
class AbsoluteStorage:
    """Variable stored at an absolute CPU address."""

    address: int

    def __post_init__(self) -> None:
        if not 0 <= self.address <= 0xFFFF:
            raise ValueError("absolute storage address must be a CPU address")


@dataclass(frozen=True)
class StackStorage:
    """Canonical CDB stack offset, without frame-address calculation."""

    offset: int


@dataclass(frozen=True)
class RegisterStorage:
    """Registers ordered from least to most significant byte."""

    registers: Tuple[str, ...]

    def __post_init__(self) -> None:
        registers = tuple(self.registers)
        if not registers or any(not name for name in registers):
            raise ValueError("register storage requires named registers")
        object.__setattr__(self, "registers", registers)


@dataclass(frozen=True)
class UnknownStorage:
    """Storage that cannot be materialized, with a structured reason."""

    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("unknown storage requires a reason")


Storage = Union[AbsoluteStorage, StackStorage, RegisterStorage, UnknownStorage]


@dataclass(frozen=True)
class Field:
    """Field of a composite type."""

    name: str
    type_id: TypeId
    offset: int

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("field name must not be empty")
        if self.offset < 0:
            raise ValueError("field offset must not be negative")


@dataclass(frozen=True)
class TypeDef:
    """Type definition whose graph edges are represented by ``TypeId``."""

    id: TypeId
    name: str
    category: str
    size: Optional[int] = None
    signed: Optional[bool] = None
    referenced_type: Optional[TypeId] = None
    fields: Tuple[Field, ...] = ()
    array_count: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.name or not self.category:
            raise ValueError("type name and category must not be empty")
        if self.size is not None and self.size < 0:
            raise ValueError("type size must not be negative")
        if self.array_count is not None and self.array_count < 0:
            raise ValueError("array count must not be negative")
        object.__setattr__(self, "fields", tuple(self.fields))


@dataclass(frozen=True)
class Symbol:
    """Linked symbol, including pseudo-symbols preserved from map files."""

    name: str
    address: int
    module: Optional[ModuleId]
    origin: Origin

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("symbol name must not be empty")
        if not 0 <= self.address <= 0xFFFF:
            raise ValueError("symbol address must be a CPU address")


@dataclass(frozen=True)
class Area:
    """Linked area with optional proven bounds."""

    name: str
    base: Optional[int] = None
    limit: Optional[int] = None
    evidence: Tuple[Origin, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("area name must not be empty")
        if self.base is not None and not 0 <= self.base <= 0xFFFF:
            raise ValueError("area base must be a CPU address")
        if self.limit is not None and not 0 <= self.limit <= 0x10000:
            raise ValueError("area limit must be at most 65536")
        if self.base is not None and self.limit is not None and self.base >= self.limit:
            raise ValueError("area bounds must not be empty or inverted")
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True)
class Function:
    """Function and its proven source/address extent."""

    id: FunctionId
    name: str
    entry: int
    end: Optional[int] = None
    end_provenance: Optional[str] = None
    lines: Tuple[SourceSpan, ...] = ()
    blocks: Tuple[AddressRange, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("function name must not be empty")
        if not 0 <= self.entry <= 0xFFFF:
            raise ValueError("function entry must be a CPU address")
        if self.end is not None and not self.entry < self.end <= 0x10000:
            raise ValueError("function end must follow its entry")
        object.__setattr__(self, "lines", tuple(self.lines))
        object.__setattr__(self, "blocks", tuple(self.blocks))


@dataclass(frozen=True)
class Variable:
    """Variable declaration and its unmaterialized storage."""

    id: VariableId
    name: str
    function: Optional[FunctionId]
    block: Optional[int]
    type_id: Optional[TypeId]
    storage: Storage
    is_parameter: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("variable name must not be empty")
        if self.block is not None and self.block < 0:
            raise ValueError("variable block must not be negative")


@dataclass(frozen=True)
class Module:
    """Reconciled module belonging to exactly one image."""

    id: ModuleId
    name: str
    areas: Tuple[Area, ...] = ()
    labels: Tuple[Symbol, ...] = ()
    exports: Tuple[Symbol, ...] = ()
    lines: Tuple[SourceSpan, ...] = ()

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("module name must not be empty")
        for attribute in ("areas", "labels", "exports", "lines"):
            object.__setattr__(self, attribute, tuple(getattr(self, attribute)))


@dataclass(frozen=True)
class CodeLocation:
    """Resolved CPU location with all available offline evidence."""

    image: ImageId
    address: int
    module: Optional[ModuleId] = None
    area: Optional[str] = None
    offset: int = 0
    source: Optional[SourceSpan] = None
    function: Optional[FunctionId] = None
    evidence: Tuple[Origin, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.address <= 0xFFFF:
            raise ValueError("code location address must be a CPU address")
        if self.module is not None and self.module.image != self.image:
            raise ValueError("code location image and module image must agree")
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True)
class Image:
    """All reconciled offline information for one linked image."""

    id: ImageId
    modules: Tuple[Module, ...] = ()
    symbols: Tuple[Symbol, ...] = ()
    functions: Tuple[Function, ...] = ()
    variables: Tuple[Variable, ...] = ()
    types: Tuple[TypeDef, ...] = ()
    diagnostics: Tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        for attribute in (
            "modules",
            "symbols",
            "functions",
            "variables",
            "types",
            "diagnostics",
        ):
            object.__setattr__(self, attribute, tuple(getattr(self, attribute)))


class ResolutionStatus:
    """Stable status values used by ``Resolution``."""

    UNIQUE = "unique"
    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Resolution(Generic[T]):
    """Explicit unique, missing, or ambiguous query result."""

    status: str
    candidates: Tuple[T, ...] = ()
    diagnostics: Tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        candidates = tuple(self.candidates)
        diagnostics = tuple(self.diagnostics)
        valid_statuses = (
            ResolutionStatus.UNIQUE,
            ResolutionStatus.MISSING,
            ResolutionStatus.AMBIGUOUS,
        )
        if self.status not in valid_statuses:
            raise ValueError("invalid resolution status")
        if self.status == ResolutionStatus.UNIQUE and len(candidates) != 1:
            raise ValueError("unique resolution requires exactly one candidate")
        if self.status == ResolutionStatus.MISSING and candidates:
            raise ValueError("missing resolution cannot contain candidates")
        if self.status == ResolutionStatus.AMBIGUOUS and len(candidates) < 2:
            raise ValueError("ambiguous resolution requires at least two candidates")
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(self, "diagnostics", diagnostics)

    def unique_or_none(self) -> Optional[T]:
        """Return the sole candidate without erasing this result's status."""

        if self.status == ResolutionStatus.UNIQUE:
            return self.candidates[0]
        return None


__all__ = [
    "AbsoluteStorage",
    "AddressRange",
    "Area",
    "CodeLocation",
    "Field",
    "Function",
    "FunctionId",
    "Image",
    "ImageId",
    "Module",
    "ModuleId",
    "RegisterStorage",
    "Resolution",
    "ResolutionStatus",
    "SourceSpan",
    "StackStorage",
    "Storage",
    "Symbol",
    "TypeDef",
    "TypeId",
    "UnknownStorage",
    "Variable",
    "VariableId",
]
