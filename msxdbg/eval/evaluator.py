"""Expression evaluation facade contracts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple
from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import Variable
from msxdbg.session.state import InspectionContext
from .ast import (AddressOf, Binary, BuiltinCall, Dereference, Expr, Group,
                  Index, Indirect, Member, Name, Number, Unary)
from .parser import EvaluationMode, PrintRequest
from .values import (AddressValue, LValue, ScalarValue, ValueDecoder, ValueLimits,
                     ValueResult, VariableRow)
from msxdbg.debuginfo.model import ResolutionStatus, TypeId
from msxdbg.session.results import LocationResult

@dataclass(frozen=True)
class EvaluationRequirements:
    needs_live_context: bool
    needs_types: bool

class EvaluationError(Exception): pass
class UnknownName(EvaluationError): pass
class AmbiguousName(EvaluationError): pass
class UnknownType(EvaluationError): pass
class InvalidOperation(EvaluationError): pass

class Evaluator:
    def __init__(self, project: Project, decoder: ValueDecoder, limits: ValueLimits) -> None:
        self._project, self._decoder, self._limits = project, decoder, limits
    def evaluate_address(self, expression: Expr, context: InspectionContext) -> int:
        return self._integer(expression, context) & 0xFFFF
    def requirements(self, request: PrintRequest) -> EvaluationRequirements:
        live = request.mode in (EvaluationMode.READ_MEMORY, EvaluationMode.INSPECT_VARIABLE)
        return EvaluationRequirements(live or self._needs_context(request.expression), request.type_name is not None)
    def evaluate_print(self, request: PrintRequest, context: Optional[InspectionContext] = None) -> ValueResult:
        needs = self.requirements(request)
        if needs.needs_live_context and context is None:
            raise InvalidOperation("expression requires a stopped target")
        mode = request.mode
        if mode == EvaluationMode.INSPECT_VARIABLE and isinstance(request.expression, Name):
            symbol = self._project.lookup_symbol(request.expression.value)
            if symbol.status == ResolutionStatus.UNIQUE:
                mode = EvaluationMode.READ_MEMORY
            elif context is not None:
                variable = self._project.find_variable(request.expression.value,
                                                       context.symbol_context)
                if variable.status == ResolutionStatus.AMBIGUOUS:
                    raise AmbiguousName(request.expression.value)
                if variable.status == ResolutionStatus.UNIQUE:
                    return self.evaluate_variables(variable.candidates, context)[0].result
                try:
                    value = context.registers.get(request.expression.value)
                except KeyError:
                    raise UnknownName(request.expression.value) from None
                return ValueResult(ScalarValue(value, TypeId("u16"), b""), "calculation", 10,
                                   warnings=("register value has no inferred C type",))
        if mode == EvaluationMode.READ_MEMORY:
            if context is None:
                raise InvalidOperation("memory read requires a stopped target")
            expression = request.expression.address if isinstance(request.expression, Indirect) else request.expression
            if request.type_name is None and isinstance(expression, Name):
                symbol = self._project.lookup_symbol(expression.value).unique_or_none()
                if symbol is not None and self._project.is_listing_only_symbol(symbol):
                    raise UnknownType(
                        f"listing-only symbol {expression.value} requires an explicit type")
            type_name = request.type_name or (request.expression.type_name if isinstance(request.expression, Indirect) else "u8")
            resolution = self._project.lookup_type(type_name)
            if resolution.status == ResolutionStatus.MISSING: raise UnknownType(type_name)
            if resolution.status == ResolutionStatus.AMBIGUOUS: raise AmbiguousName(type_name)
            type = resolution.candidates[0]
            if (getattr(context, "signature_status", "not-configured") == "pending"
                    and type.id.image is not None):
                raise InvalidOperation("image-dependent C interpretation is unavailable until the program signature is verified")
            if type.size is None: raise UnknownType(type_name)
            if isinstance(expression, Index):
                address = (self._integer(expression.expression, context)
                           + self._integer(expression.index, context) * type.size) & 0xFFFF
            else:
                address = self.evaluate_address(expression, context)
            data = context.read_memory(address, type.size)
            value = self._decoder.decode(data, type, self._project, self._limits)
            return ValueResult(value, "memory", 10, LocationResult(address=address))
        if mode != EvaluationMode.CALCULATE:
            raise InvalidOperation("variable printing is not implemented yet")
        if self._has_typed_operator(request.expression):
            result = self._typed(request.expression, context)
            if isinstance(result, LValue):
                value = self._materialize(result, context)
                return ValueResult(value, "variable", 10, result.location)
            if isinstance(result, AddressValue):
                return ValueResult(result, "calculation", 16)
            if isinstance(result, ScalarValue):
                return ValueResult(result, "calculation", 10)
            raise InvalidOperation("typed expression produced no value")
        value = self._integer(request.expression, context)
        base = 10
        if isinstance(request.expression, BuiltinCall):
            base = 16 if request.expression.name == "hex" else 2
        return ValueResult(ScalarValue(value, TypeId("int"), b""), "calculation", base)
    def evaluate_variables(self, variables: Sequence[Variable], context: InspectionContext) -> Tuple[VariableRow, ...]:
        if getattr(context, "signature_status", "not-configured") == "pending":
            raise InvalidOperation("C interpretation is unavailable until the program signature is verified")
        rows = []
        for variable in variables:
            location = context.locate_variable(variable)
            if location.unavailable_reason is not None:
                rows.append(VariableRow(variable, location,
                    ValueResult(None, "variable", 10, location,
                                location.unavailable_reason)))
                continue
            if variable.type_id is None:
                reason = "variable has no known type"
                rows.append(VariableRow(variable, location,
                    ValueResult(None, "variable", 10, location, reason)))
                continue
            try:
                type = self._project.type_by_id(variable.type_id)
                if type.size is None:
                    raise ValueError("incomplete type")
                data = (location.register_bytes if location.register_bytes is not None
                        else context.read_memory(location.address, type.size))
                value = self._decoder.decode(data, type, self._project, self._limits)
            except (KeyError, ValueError) as error:
                reason = str(error) or "value is unavailable"
                rows.append(VariableRow(variable, location,
                    ValueResult(None, "variable", 10, location, reason)))
                continue
            warnings = (("register live range is not proven",)
                        if location.register_bytes is not None else ())
            rows.append(VariableRow(variable, location,
                ValueResult(value, "variable", 10, location, warnings=warnings)))
        context.validate()
        return tuple(rows)

    def _needs_context(self, expression: Expr) -> bool:
        if isinstance(expression, Number): return False
        if isinstance(expression, Name):
            return self._project.lookup_symbol(expression.value).status != ResolutionStatus.UNIQUE
        if isinstance(expression, (Group, Unary)): return self._needs_context(expression.expression if isinstance(expression, Group) else expression.operand)
        if isinstance(expression, Binary): return self._needs_context(expression.left) or self._needs_context(expression.right)
        if isinstance(expression, BuiltinCall): return any(self._needs_context(item) for item in expression.arguments)
        if isinstance(expression, (AddressOf, Dereference, Member, Index)): return True
        return True

    def _has_typed_operator(self, expression: Expr) -> bool:
        if isinstance(expression, (AddressOf, Dereference, Member)): return True
        if isinstance(expression, Index): return True
        if isinstance(expression, Group): return self._has_typed_operator(expression.expression)
        if isinstance(expression, Unary): return self._has_typed_operator(expression.operand)
        if isinstance(expression, Binary):
            return self._has_typed_operator(expression.left) or self._has_typed_operator(expression.right)
        if isinstance(expression, BuiltinCall):
            return any(self._has_typed_operator(item) for item in expression.arguments)
        return False

    def _typed(self, expression: Expr, context: Optional[InspectionContext]):
        if context is None:
            raise InvalidOperation("typed C expression requires a stopped target")
        if getattr(context, "signature_status", "not-configured") == "pending":
            raise InvalidOperation("C interpretation is unavailable until the program signature is verified")
        if isinstance(expression, Group):
            return self._typed(expression.expression, context)
        if isinstance(expression, Name):
            variable = self._project.find_variable(expression.value, context.symbol_context)
            if variable.status == ResolutionStatus.AMBIGUOUS:
                raise AmbiguousName(expression.value)
            if variable.status == ResolutionStatus.UNIQUE:
                item = variable.candidates[0]
                if item.type_id is None:
                    raise UnknownType(f"variable {item.name} has no known type")
                location = context.locate_variable(item)
                if location.unavailable_reason is not None:
                    raise InvalidOperation(location.unavailable_reason)
                return LValue(item.type_id, location)
            symbol = self._project.lookup_symbol(expression.value)
            if symbol.status == ResolutionStatus.AMBIGUOUS:
                raise AmbiguousName(expression.value)
            if symbol.status == ResolutionStatus.UNIQUE:
                return AddressValue(symbol.candidates[0].address)
            try:
                return ScalarValue(context.registers.get(expression.value), TypeId("u16"), b"")
            except KeyError:
                raise UnknownName(expression.value) from None
        if isinstance(expression, Number):
            return ScalarValue(expression.value, TypeId("int"), b"")
        if isinstance(expression, AddressOf):
            operand = self._typed(expression.expression, context)
            if not isinstance(operand, LValue) or operand.location.address is None:
                raise InvalidOperation("address-of requires a memory-backed lvalue")
            return AddressValue(operand.location.address, operand.type_id)
        if isinstance(expression, Dereference):
            return self._dereference(self._typed(expression.expression, context), context)
        if isinstance(expression, Index):
            base = self._typed(expression.expression, context)
            index = self._integer(expression.index, context)
            if isinstance(base, LValue):
                base_type = self._project.type_by_id(base.type_id)
                if base_type.category == "array":
                    if base_type.referenced_type is None or base.location.address is None:
                        raise InvalidOperation("array location or element type is unavailable")
                    if base_type.array_count is not None and not 0 <= index < base_type.array_count:
                        raise InvalidOperation("array index is outside the proven bounds")
                    child = self._project.type_by_id(base_type.referenced_type)
                    if child.size is None:
                        raise InvalidOperation("array element size is unavailable")
                    return LValue(child.id, LocationResult(
                        address=base.location.address + index * child.size))
                if base_type.category == "pointer":
                    return self._index_pointer(base, index, context)
            if isinstance(base, AddressValue) and base.referenced_type is not None:
                child = self._project.type_by_id(base.referenced_type)
                if child.size is None: raise InvalidOperation("element size is unavailable")
                return LValue(child.id, LocationResult(address=base.address + index * child.size))
            raise InvalidOperation("indexing requires a typed array or pointer")
        if isinstance(expression, Member):
            base = self._typed(expression.expression, context)
            if expression.through_pointer:
                base = self._dereference(base, context)
            if not isinstance(base, LValue) or base.location.address is None:
                raise InvalidOperation("member access requires a memory-backed struct")
            type_ = self._project.type_by_id(base.type_id)
            if type_.category != "struct":
                raise InvalidOperation("member access requires a struct type")
            fields = [item for item in type_.fields if item.name == expression.name]
            if len(fields) != 1:
                raise InvalidOperation(f"unknown or ambiguous field: {expression.name}")
            field = fields[0]
            return LValue(field.type_id,
                          LocationResult(address=base.location.address + field.offset))
        # Arithmetic containing typed operands materializes them to integers.
        return ScalarValue(self._integer(expression, context), TypeId("int"), b"")

    def _dereference(self, value, context):
        if isinstance(value, LValue):
            type_ = self._project.type_by_id(value.type_id)
            if type_.category != "pointer" or type_.referenced_type is None:
                raise InvalidOperation("dereference requires a typed pointer")
            scalar = self._materialize(value, context)
            if not isinstance(scalar, ScalarValue) or not isinstance(scalar.value, int):
                raise InvalidOperation("pointer value is unavailable")
            if not 0 <= scalar.value <= 0xFFFF:
                raise InvalidOperation("pointer lies outside the Z80 address space")
            return LValue(type_.referenced_type, LocationResult(address=scalar.value))
        if isinstance(value, AddressValue) and value.referenced_type is not None:
            return LValue(value.referenced_type, LocationResult(address=value.address))
        raise InvalidOperation("dereference requires a typed pointer")

    def _index_pointer(self, base, index, context):
        type_ = self._project.type_by_id(base.type_id)
        child = self._project.type_by_id(type_.referenced_type)
        if child.size is None: raise InvalidOperation("pointer element size is unavailable")
        scalar = self._materialize(base, context)
        address = scalar.value + index * child.size
        if not 0 <= address <= 0xFFFF:
            raise InvalidOperation("pointer index lies outside the Z80 address space")
        return LValue(child.id, LocationResult(address=address))

    def _materialize(self, value: LValue, context: InspectionContext):
        type_ = self._project.type_by_id(value.type_id)
        if type_.size is None: raise InvalidOperation("value type is incomplete")
        if value.location.register_bytes is not None:
            data = value.location.register_bytes
        elif value.location.address is not None:
            if value.location.address + type_.size > 0x10000:
                raise InvalidOperation("value crosses the Z80 address-space boundary")
            data = context.read_memory(value.location.address, type_.size)
        else:
            raise InvalidOperation(value.location.unavailable_reason or "value location is unavailable")
        return self._decoder.decode(data, type_, self._project, self._limits)

    def _integer(self, expression: Expr, context: Optional[InspectionContext]) -> int:
        if isinstance(expression, Number): return expression.value
        if isinstance(expression, Group): return self._integer(expression.expression, context)
        if isinstance(expression, Unary):
            value=self._integer(expression.operand, context)
            return {"+": lambda: value, "-": lambda: -value, "~": lambda: ~value}[expression.operator]()
        if isinstance(expression, Name):
            symbol=self._project.lookup_symbol(expression.value)
            if symbol.status == ResolutionStatus.UNIQUE: return symbol.candidates[0].address
            if symbol.status == ResolutionStatus.AMBIGUOUS: raise AmbiguousName(expression.value)
            if context is None: raise UnknownName(expression.value)
            if hasattr(context, "symbol_context"):
                variable = self._project.find_variable(expression.value, context.symbol_context)
                if variable.status == ResolutionStatus.AMBIGUOUS:
                    raise AmbiguousName(expression.value)
                if variable.status == ResolutionStatus.UNIQUE:
                    result = self.evaluate_variables(variable.candidates, context)[0].result
                    if result.unavailable_reason is not None:
                        raise InvalidOperation(result.unavailable_reason)
                    if not isinstance(result.value, ScalarValue) or not isinstance(result.value.value, (int, bool)):
                        raise InvalidOperation(f"variable {expression.value} is not an integer scalar")
                    return int(result.value.value)
            try: return context.registers.get(expression.value)
            except KeyError: raise UnknownName(expression.value) from None
        if isinstance(expression, (AddressOf, Dereference, Member, Index)):
            value = self._typed(expression, context)
            if isinstance(value, AddressValue): return value.address
            if isinstance(value, LValue): value = self._materialize(value, context)
            if isinstance(value, ScalarValue) and isinstance(value.value, (int, bool)):
                return int(value.value)
            raise InvalidOperation("typed expression is not an integer scalar")
        if isinstance(expression, Binary):
            left=self._integer(expression.left,context); right=self._integer(expression.right,context)
            if expression.operator in ("/","%") and right == 0: raise InvalidOperation("division by zero")
            operations={"+":lambda:left+right,"-":lambda:left-right,"*":lambda:left*right,
                "/":lambda:(-1 if (left<0) != (right<0) else 1)*(abs(left)//abs(right)),
                "%":lambda:left-((-1 if (left<0)!=(right<0) else 1)*(abs(left)//abs(right)))*right,
                "<<":lambda:left<<right,">>":lambda:left>>right,"&":lambda:left&right,
                "^":lambda:left^right,"|":lambda:left|right}
            try: return operations[expression.operator]()
            except (KeyError, ValueError): raise InvalidOperation(expression.operator) from None
        if isinstance(expression, BuiltinCall):
            if len(expression.arguments) != 1: raise InvalidOperation(f"{expression.name}() expects one argument")
            return self._integer(expression.arguments[0],context)
        if isinstance(expression, Indirect): return self._integer(expression.address,context)
        raise InvalidOperation(type(expression).__name__)

__all__ = ["AmbiguousName", "EvaluationError", "EvaluationRequirements", "Evaluator", "InvalidOperation", "UnknownName", "UnknownType"]
