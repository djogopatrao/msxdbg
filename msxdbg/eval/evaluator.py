"""Expression evaluation facade contracts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple
from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import Variable
from msxdbg.session.state import InspectionContext
from .ast import Expr
from .parser import PrintRequest
from .values import ValueDecoder, ValueLimits, ValueResult, VariableRow

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
        raise NotImplementedError("Evaluator.evaluate_address is not implemented")
    def requirements(self, request: PrintRequest) -> EvaluationRequirements:
        raise NotImplementedError("Evaluator.requirements is not implemented")
    def evaluate_print(self, request: PrintRequest, context: Optional[InspectionContext] = None) -> ValueResult:
        raise NotImplementedError("Evaluator.evaluate_print is not implemented")
    def evaluate_variables(self, variables: Sequence[Variable], context: InspectionContext) -> Tuple[VariableRow, ...]:
        raise NotImplementedError("Evaluator.evaluate_variables is not implemented")

__all__ = ["AmbiguousName", "EvaluationError", "EvaluationRequirements", "Evaluator", "InvalidOperation", "UnknownName", "UnknownType"]
