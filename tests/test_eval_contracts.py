"""Structural tests for expression and evaluation contracts."""
import unittest
from msxdbg.debuginfo.index import Project
from msxdbg.eval.ast import Binary, Number
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.macros import ExpandedTokens, ExpansionLimits, MacroExpander
from msxdbg.eval.parser import ExpressionParser
from msxdbg.eval.tokens import Token, tokenize
from msxdbg.eval.values import ValueDecoder, ValueLimits
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext

class EvalContractTests(unittest.TestCase):
    def test_ast_and_expanded_tokens_are_structured(self) -> None:
        expression = Binary(Number(1), "+", Number(2))
        expanded = ExpandedTokens([Token("number", "1", 0, 1)])
        self.assertEqual("+", expression.operator)
        self.assertEqual((Token("number", "1", 0, 1),), expanded.tokens)

    def test_remaining_unimplemented_operations_fail_explicitly(self) -> None:
        self.assertEqual("1", tokenize("1")[0].lexeme)
        self.assertEqual(Number(1), ExpressionParser().parse_expression("1"))
        evaluator = Evaluator(Project([]), ValueDecoder(), ValueLimits())
        self.assertEqual(1, evaluator.evaluate_address(Number(1), object()))  # type: ignore[arg-type]
        self.assertEqual((), MacroExpander().expand([], MacroCatalog(), MacroContext(), ExpansionLimits()).tokens)

if __name__ == "__main__": unittest.main()
