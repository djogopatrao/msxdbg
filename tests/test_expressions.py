"""Tokenizer, parser, and integer evaluator tests."""

import pytest
from pathlib import Path

from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.diagnostics import Origin
from msxdbg.debuginfo.model import Image, ImageId, Symbol
from msxdbg.eval.ast import Binary, BuiltinCall, Group, Indirect, Name, Number, Unary
from msxdbg.eval.evaluator import Evaluator, InvalidOperation, UnknownName
from msxdbg.eval.macros import ExpandedTokens
from msxdbg.eval.parser import EvaluationMode, ExpressionParser
from msxdbg.eval.tokens import ExpressionSyntaxError, tokenize
from msxdbg.eval.values import ValueDecoder, ValueLimits
from msxdbg.target.api import RegisterSet


class Context:
    registers = RegisterSet({"PC": 0x1234, "HL": 0x8000})


def evaluator(): return Evaluator(Project(()), ValueDecoder(), ValueLimits())


def test_tokenize_numbers_names_operators_and_spans():
    tokens = tokenize(" 0x10 + #2a << HL ")
    assert [token.lexeme for token in tokens] == ["0x10", "+", "#2a", "<<", "HL"]
    assert (tokens[0].start, tokens[0].end) == (1, 5)
    assert (tokens[-1].start, tokens[-1].end) == (15, 17)


@pytest.mark.parametrize("text", ["0x", "#", "1 @ 2"])
def test_tokenize_reports_invalid_span(text):
    with pytest.raises(ExpressionSyntaxError) as error:
        tokenize(text)
    assert error.value.end >= error.value.start


def test_parser_precedence_associativity_and_grouping():
    parser = ExpressionParser()
    assert parser.parse_expression("1+2*3") == Binary(Number(1), "+", Binary(Number(2), "*", Number(3)))
    assert parser.parse_expression("8-3-2") == Binary(Binary(Number(8), "-", Number(3)), "-", Number(2))
    assert parser.parse_expression("-(1+2)") == Unary("-", Group(Binary(Number(1), "+", Number(2))))


def test_parser_indirect_builtin_and_rejects_arbitrary_calls():
    parser = ExpressionParser()
    assert parser.parse_expression("[HL+3]") == Indirect(Binary(Name("HL"), "+", Number(3)), "u8")
    assert parser.parse_expression("hex(16)") == BuiltinCall("hex", (Number(16),))
    with pytest.raises(ExpressionSyntaxError): parser.parse_expression("system(1)")


@pytest.mark.parametrize("text", ["", "(1+2", "1 2", "1+"])
def test_parser_rejects_incomplete_or_extra_input(text):
    with pytest.raises(ExpressionSyntaxError): ExpressionParser().parse_expression(text)


def test_parse_print_classifies_calculation_memory_and_name():
    parser = ExpressionParser()
    expanded = lambda text: ExpandedTokens(tokenize(text))
    assert parser.parse_print(expanded("1+2")).mode == EvaluationMode.CALCULATE
    assert parser.parse_print(expanded("[HL]")).mode == EvaluationMode.READ_MEMORY
    assert parser.parse_print(expanded("counter")).mode == EvaluationMode.INSPECT_VARIABLE


def test_evaluator_integer_arithmetic_registers_and_address_wrap():
    parser = ExpressionParser(); subject = evaluator()
    assert subject.evaluate_address(parser.parse_expression("PC+2"), Context()) == 0x1236
    assert subject.evaluate_address(parser.parse_expression("-1"), Context()) == 0xFFFF
    request = parser.parse_print(ExpandedTokens(tokenize("5+3*2")))
    assert subject.evaluate_print(request).value.value == 11


def test_evaluator_uses_exact_integer_division_and_reports_errors():
    parser = ExpressionParser(); subject = evaluator()
    huge = "1000000000000000000000000000001/3"
    request = parser.parse_print(ExpandedTokens(tokenize(huge)))
    assert subject.evaluate_print(request).value.value == 333333333333333333333333333333
    with pytest.raises(InvalidOperation): subject.evaluate_print(parser.parse_print(ExpandedTokens(tokenize("1/0"))))
    with pytest.raises(UnknownName): subject.evaluate_address(Name("missing"), None)


def test_requirements_distinguish_constant_from_live_register():
    parser = ExpressionParser(); subject = evaluator()
    constant = parser.parse_print(ExpandedTokens(tokenize("1+2")))
    register = parser.parse_print(ExpandedTokens(tokenize("PC+2")))
    assert not subject.requirements(constant).needs_live_context
    assert subject.requirements(register).needs_live_context


class MemoryContext(Context):
    def __init__(self, memory): self.memory = memory; self.reads = []
    def read_memory(self, address, size):
        self.reads.append((address, size))
        return self.memory[address:address+size]


def test_evaluate_print_reads_explicit_memory_with_requested_type():
    parser = ExpressionParser(); subject = evaluator()
    context = MemoryContext(bytes(range(256)) * 256)
    request = parser.parse_print(ExpandedTokens(tokenize("[0x102]")), "u16")
    result = subject.evaluate_print(request, context)
    assert result.kind == "memory"
    assert result.value.value == 0x0302
    assert result.location.address == 0x102
    assert context.reads == [(0x102, 2)]


def test_isolated_map_symbol_reads_u8_but_symbol_arithmetic_does_not():
    symbol = Symbol("_x", 0x100, None, Origin(Path("map")))
    project = Project((Image(ImageId("app"), symbols=(symbol,)),))
    subject = Evaluator(project, ValueDecoder(), ValueLimits())
    parser = ExpressionParser(); context = MemoryContext(bytes(range(256)) * 256)
    isolated = parser.parse_print(ExpandedTokens(tokenize("_x")))
    assert subject.evaluate_print(isolated, context).value.value == 0
    arithmetic = parser.parse_print(ExpandedTokens(tokenize("_x+1")))
    assert subject.evaluate_print(arithmetic).value.value == 0x101
    assert context.reads == [(0x100, 1)]


def test_typed_index_scales_by_element_size():
    symbol = Symbol("_tiles", 0x100, None, Origin(Path("map")))
    project = Project((Image(ImageId("app"), symbols=(symbol,)),))
    subject = Evaluator(project, ValueDecoder(), ValueLimits())
    parser = ExpressionParser(); context = MemoryContext(bytes(range(256)) * 256)
    request = parser.parse_print(ExpandedTokens(tokenize("_tiles[3]")), "u16")
    result = subject.evaluate_print(request, context)
    assert result.location.address == 0x106
    assert context.reads == [(0x106, 2)]
