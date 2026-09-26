"""Decoded-value and presentation-neutral result contracts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple, Union
from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import Resolution, Storage, TypeDef, TypeId, Variable
from msxdbg.session.results import LocationResult

@dataclass(frozen=True)
class ScalarValue: value: object; type_id: TypeId; raw_bytes: bytes
@dataclass(frozen=True)
class AddressValue: address: int; referenced_type: Optional[TypeId] = None
@dataclass(frozen=True)
class LValue: type_id: TypeId; storage: Storage
@dataclass(frozen=True)
class StringValue: text: str; nul_terminated: bool; truncated: bool; raw_bytes: bytes
@dataclass(frozen=True)
class ArrayValue: items: Tuple["DecodedValue", ...]; truncated: bool = False
@dataclass(frozen=True)
class StructValue: fields: Tuple[Tuple[str, "DecodedValue"], ...]

DecodedValue = Union[ScalarValue, StringValue, ArrayValue, StructValue]

@dataclass(frozen=True)
class ValueLimits:
    max_string: int = 256
    max_elements: int = 16
    max_composite_bytes: int = 4096

@dataclass(frozen=True)
class ValueResult:
    value: Optional[DecodedValue]
    kind: str
    display_base: int
    location: Optional[LocationResult] = None
    unavailable_reason: Optional[str] = None
    warnings: Tuple[str, ...] = ()
    def __post_init__(self) -> None: object.__setattr__(self, "warnings", tuple(self.warnings))

@dataclass(frozen=True)
class VariableRow:
    variable: Variable
    location: LocationResult
    result: ValueResult

class ValueDecoder:
    def decode(self, data: bytes, type: TypeDef, types: Project, limits: ValueLimits) -> DecodedValue:
        raise NotImplementedError("ValueDecoder.decode is not implemented")

def default_print_type(variable: Variable, project: Project) -> Resolution[TypeDef]:
    raise NotImplementedError("eval.default_print_type is not implemented")

__all__ = ["AddressValue", "ArrayValue", "DecodedValue", "LValue", "ScalarValue", "StringValue", "StructValue", "ValueDecoder", "ValueLimits", "ValueResult", "VariableRow", "default_print_type"]
