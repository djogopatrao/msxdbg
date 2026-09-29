"""Decoded-value and presentation-neutral result contracts."""
from __future__ import annotations
from dataclasses import dataclass
import math
import struct
from typing import Optional, Tuple, Union
from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import Resolution, ResolutionStatus, Storage, TypeDef, TypeId, Variable
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
        return self._decode(bytes(data), type, types, limits, set())

    def _decode(self, data, type, types, limits, active):
        if type.size is None:
            raise ValueError(f"incomplete type: {type.name}")
        if type.size > limits.max_composite_bytes:
            raise ValueError("value exceeds composite byte limit")
        if len(data) < type.size:
            raise ValueError(f"{type.name} requires {type.size} bytes, got {len(data)}")
        raw = data[:type.size]
        if type.category in ("integer", "character", "pointer"):
            value = int.from_bytes(raw, "little", signed=bool(type.signed))
            if type.name == "bool": value = bool(value)
            return ScalarValue(value, type.id, raw)
        if type.category == "float":
            if type.size != 4: raise ValueError("unsupported floating-point width")
            value = struct.unpack("<f", raw)[0]
            if not math.isfinite(value):
                value = {"value": None, "classification": "nan" if math.isnan(value) else ("+infinity" if value > 0 else "-infinity")}
            return ScalarValue(value, type.id, raw)
        if type.category == "void":
            raise ValueError("void has no value")
        if type.id in active:
            raise ValueError(f"recursive value type: {type.name}")
        active = active | {type.id}
        if type.category == "array":
            if type.referenced_type is None or type.array_count is None:
                raise ValueError("incomplete array type")
            child = types.type_by_id(type.referenced_type)
            if child.size is None or child.size == 0: raise ValueError("invalid array element type")
            count = min(type.array_count, limits.max_elements)
            if child.category == "character" and child.size == 1:
                available = raw[:min(type.array_count, limits.max_string)]
                nul = available.find(b"\0")
                content = available if nul < 0 else available[:nul]
                return StringValue(content.decode("latin-1"), nul >= 0,
                                   nul < 0 and type.array_count > limits.max_string, available)
            items = tuple(self._decode(raw[i*child.size:(i+1)*child.size], child, types, limits, active)
                          for i in range(count))
            return ArrayValue(items, type.array_count > count)
        if type.category == "struct":
            fields = []
            for field in type.fields:
                child = types.type_by_id(field.type_id)
                if child.size is None: raise ValueError(f"incomplete field: {field.name}")
                fields.append((field.name, self._decode(raw[field.offset:field.offset+child.size], child, types, limits, active)))
            return StructValue(tuple(fields))
        raise ValueError(f"unsupported type category: {type.category}")

def default_print_type(variable: Variable, project: Project) -> Resolution[TypeDef]:
    if variable.type_id is None:
        return Resolution(ResolutionStatus.MISSING)
    try:
        type = project.type_by_id(variable.type_id)
    except KeyError:
        return Resolution(ResolutionStatus.MISSING)
    if type.category not in ("integer", "character", "float") or type.size is None:
        return Resolution(ResolutionStatus.MISSING)
    return Resolution(ResolutionStatus.UNIQUE, (type,))

__all__ = ["AddressValue", "ArrayValue", "DecodedValue", "LValue", "ScalarValue", "StringValue", "StructValue", "ValueDecoder", "ValueLimits", "ValueResult", "VariableRow", "default_print_type"]
