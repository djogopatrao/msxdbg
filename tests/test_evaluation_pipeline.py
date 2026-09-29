"""End-to-end expression pipeline tests."""

from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext, MacroDefinition, MacroToken
from msxdbg.debuginfo.diagnostics import Origin
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.service import EvaluationPipeline
from msxdbg.eval.values import ValueDecoder, ValueLimits
from msxdbg.target.api import RegisterSet
from pathlib import Path


class Context:
    registers = RegisterSet({"HL": 0x8000})
    def __init__(self): self.reads = []
    def read_memory(self, address, size):
        self.reads.append((address, size)); return b"\x34\x12"[:size]


def pipeline():
    project = Project(())
    return EvaluationPipeline(project, Evaluator(project, ValueDecoder(), ValueLimits()))


def test_constant_pipeline_does_not_request_inspection():
    calls = []
    result = pipeline().evaluate_print("2 + 3 * 4", MacroCatalog(), MacroContext(),
                                       lambda: calls.append(1))
    assert result.value.value == 14
    assert calls == []


def test_pipeline_expands_macros_before_parsing():
    definition = MacroDefinition("OFFSET", None, (MacroToken("2"), MacroToken("+"), MacroToken("3")),
                                 Origin(Path("config.h"), 1, "define"), MacroContext())
    result = pipeline().evaluate_print("OFFSET*4", MacroCatalog((definition,)), MacroContext())
    assert result.value.value == 14


def test_live_pipeline_acquires_exactly_one_context():
    context = Context(); calls = []
    def provide(): calls.append(1); return context
    result = pipeline().evaluate_print("HL+1", MacroCatalog(), MacroContext(), provide)
    assert result.value.value == 0x8001
    assert calls == [1]


def test_typed_memory_pipeline_uses_macro_address_and_cache_capable_context():
    definition = MacroDefinition("BASE", None, (MacroToken("0x8000"),),
                                 Origin(Path("config.h"), 1, "define"), MacroContext())
    context = Context()
    result = pipeline().evaluate_print("[BASE]", MacroCatalog((definition,)),
                                       MacroContext(), lambda: context, "u16")
    assert result.value.value == 0x1234
    assert context.reads == [(0x8000, 2)]
