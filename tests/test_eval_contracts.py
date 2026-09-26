"""Structural tests for expression and evaluation contracts."""
import unittest
from msxdbg.debuginfo.index import Project
from msxdbg.eval.ast import Binary, Number
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.macros import ExpandedTokens, ExpansionLimits, MacroExpander
from msxdbg.eval.parser import ExpressionParser
from msxdbg.eval.tokens import Token, tokenize
from msxdbg.eval.values import ValueDecoder, ValueLimits

class EvalContractTests(unittest.TestCase):
    def test_ast_and_expanded_tokens_are_structured(self) -> None:
        expression = Binary(Number(1), "+", Number(2))
        expanded = ExpandedTokens([Token("number", "1", 0, 1)])
        self.assertEqual("+", expression.operator)
        self.assertEqual((Token("number", "1", 0, 1),), expanded.tokens)

    def test_unimplemented_operations_fail_explicitly(self) -> None:
        with self.assertRaises(NotImplementedError): tokenize("1")
        with self.assertRaises(NotImplementedError): ExpressionParser().parse_expression("1")
        evaluator = Evaluator(Project([]), ValueDecoder(), ValueLimits())
        with self.assertRaises(NotImplementedError): evaluator.evaluate_address(Number(1), object())  # type: ignore[arg-type]
        with self.assertRaises(NotImplementedError): MacroExpander().expand([], object(), object(), ExpansionLimits())  # type: ignore[arg-type]

if __name__ == "__main__": unittest.main()
