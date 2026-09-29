"""Expression evaluation facade contracts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple
from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import Variable
from msxdbg.session.state import InspectionContext
from .ast import Binary, BuiltinCall, Expr, Group, Index, Indirect, Name, Number, Unary
from .parser import EvaluationMode, PrintRequest
from .values import ScalarValue, ValueDecoder, ValueLimits, ValueResult, VariableRow
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
            type_name = request.type_name or (request.expression.type_name if isinstance(request.expression, Indirect) else "u8")
            resolution = self._project.lookup_type(type_name)
            if resolution.status == ResolutionStatus.MISSING: raise UnknownType(type_name)
            if resolution.status == ResolutionStatus.AMBIGUOUS: raise AmbiguousName(type_name)
            type = resolution.candidates[0]
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
        value = self._integer(request.expression, context)
        base = 10
        if isinstance(request.expression, BuiltinCall):
            base = 16 if request.expression.name == "hex" else 2
        return ValueResult(ScalarValue(value, TypeId("int"), b""), "calculation", base)
    def evaluate_variables(self, variables: Sequence[Variable], context: InspectionContext) -> Tuple[VariableRow, ...]:
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
        return True

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
        if isinstance(expression, Index): return self._integer(expression.expression,context)+self._integer(expression.index,context)
        raise InvalidOperation(type(expression).__name__)

__all__ = ["AmbiguousName", "EvaluationError", "EvaluationRequirements", "Evaluator", "InvalidOperation", "UnknownName", "UnknownType"]
