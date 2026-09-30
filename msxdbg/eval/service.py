"""Application service for the complete expression-evaluation pipeline."""

from __future__ import annotations

from typing import Callable, Optional, Tuple

from msxdbg.debuginfo.index import Project, VariableKind
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext
from msxdbg.session.state import InspectionContext
from .evaluator import EvaluationRequirements, Evaluator
from .macros import ExpansionLimits, MacroExpander
from .parser import ExpressionParser, PrintRequest
from .tokens import tokenize
from .values import ValueResult, VariableRow


class EvaluationPipeline:
    def __init__(self, project: Project, evaluator: Evaluator,
                 parser: Optional[ExpressionParser] = None,
                 expander: Optional[MacroExpander] = None,
                 expansion_limits: ExpansionLimits = ExpansionLimits()) -> None:
        self._project = project
        self._evaluator = evaluator
        self._parser = parser or ExpressionParser()
        self._expander = expander or MacroExpander()
        self._expansion_limits = expansion_limits

    def prepare_print(self, text: str, macros: MacroCatalog,
                      macro_context: MacroContext,
                      type_name: Optional[str] = None
                      ) -> Tuple[PrintRequest, EvaluationRequirements]:
        tokens = tokenize(text)
        expanded = self._expander.expand(
            tokens, macros, macro_context, self._expansion_limits
        )
        request = self._parser.parse_print(expanded, type_name)
        return request, self._evaluator.requirements(request)

    def evaluate_print(self, text: str, macros: MacroCatalog,
                       macro_context: MacroContext,
                       inspection_provider: Optional[Callable[[], InspectionContext]] = None,
                       type_name: Optional[str] = None) -> ValueResult:
        request, requirements = self.prepare_print(
            text, macros, macro_context, type_name
        )
        context = None
        if requirements.needs_live_context:
            if inspection_provider is None:
                return self._evaluator.evaluate_print(request, None)
            context = inspection_provider()
        return self._evaluator.evaluate_print(request, context)

    def evaluate_variables(self, kind: str,
                           inspection_provider: Callable[[], InspectionContext]
                           ) -> Tuple[VariableRow, ...]:
        if kind not in (VariableKind.LOCALS, VariableKind.PARAMETERS):
            raise ValueError("variable table kind must be locals or parameters")
        context = inspection_provider()
        variables = self._project.variables_in_scope(context.symbol_context, kind)
        return self._evaluator.evaluate_variables(variables, context)

    def evaluate_address(self, text: str, macros: MacroCatalog,
                         macro_context: MacroContext,
                         inspection_provider: Callable[[], InspectionContext]) -> int:
        tokens = tokenize(text)
        expanded = self._expander.expand(
            tokens, macros, macro_context, self._expansion_limits
        )
        expression = self._parser.parse_expression(
            "".join(token.lexeme for token in expanded.tokens)
        )
        return self._evaluator.evaluate_address(expression, inspection_provider())


__all__ = ["EvaluationPipeline"]
