"""Variable storage materialization and table evaluation."""

from msxdbg.debuginfo.index import Project, SymbolContext
from msxdbg.debuginfo.model import (AbsoluteStorage, ImageId, ModuleId,
    Image, RegisterStorage, Resolution, ResolutionStatus, StackStorage, TypeId,
    UnknownStorage, Variable, VariableId)
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.macros import ExpandedTokens
from msxdbg.eval.parser import ExpressionParser
from msxdbg.eval.tokens import tokenize
from msxdbg.eval.values import ValueDecoder, ValueLimits
from msxdbg.session.frames import Frame, FrameService, FrameState
from msxdbg.target.api import RegisterSet


image = ImageId("app")
module = ModuleId(image, "main")


def variable(name, type_name, storage):
    return Variable(VariableId(module, name), name, None, None,
                    TypeId(type_name) if type_name else None, storage)


def frame(ix=0x9000, state=FrameState.IX_ACTIVE):
    return Frame(0, 0x100, 0x100, Resolution(ResolutionStatus.MISSING), ix, state)


def test_frame_service_materializes_all_storage_kinds():
    service = FrameService(); registers = RegisterSet({"L": 0x34, "H": 0x12})
    reader = object()
    assert service.locate(variable("a", "u8", AbsoluteStorage(0x8000)), frame(), registers, reader).address == 0x8000
    assert service.locate(variable("s", "u16", StackStorage(-2)), frame(), registers, reader).address == 0x8FFE
    result = service.locate(variable("r", "u16", RegisterStorage(("L", "H"))), frame(), registers, reader)
    assert result.register_bytes == b"\x34\x12"
    unknown = service.locate(variable("u", "u8", UnknownStorage("optimized out")), frame(), registers, reader)
    assert unknown.unavailable_reason == "optimized out"


def test_stack_location_requires_proven_frame_and_never_wraps():
    service = FrameService(); registers = RegisterSet({})
    unavailable = service.locate(variable("x", "u8", StackStorage(1)),
                                 frame(None, FrameState.UNKNOWN), registers, object())
    assert "proven IX" in unavailable.unavailable_reason
    outside = service.locate(variable("x", "u8", StackStorage(-2)),
                             frame(1), registers, object())
    assert "outside" in outside.unavailable_reason


def test_register_storage_is_unavailable_in_caller_frames():
    service = FrameService(); registers = RegisterSet({"HL": 0x1234})
    caller = Frame(1, 0x200, 0x1FF, Resolution(ResolutionStatus.MISSING),
                   0x9000, FrameState.IX_ACTIVE)
    result = service.locate(
        variable("saved", "u16", RegisterStorage(("HL",))),
        caller, registers, object(),
    )
    assert result.unavailable_reason == "register storage is unavailable in caller frames"


class Context:
    def __init__(self):
        self.frame = frame(); self.registers = RegisterSet({"L": 0x78, "H": 0x56})
        self.memory = bytearray(0x10000); self.memory[0x8000:0x8002] = b"\x34\x12"
        self.service = FrameService(); self.reads = []; self.validations = 0
        self.symbol_context = SymbolContext(image, module, None, 0x100)
    def locate_variable(self, item): return self.service.locate(item, self.frame, self.registers, self)
    def read_memory(self, address, size):
        self.reads.append((address, size)); return bytes(self.memory[address:address+size])
    def validate(self): self.validations += 1


def test_evaluate_variables_decodes_memory_and_registers_independently():
    context = Context(); evaluator = Evaluator(Project(()), ValueDecoder(), ValueLimits())
    rows = evaluator.evaluate_variables((
        variable("memory", "u16", AbsoluteStorage(0x8000)),
        variable("register", "u16", RegisterStorage(("L", "H"))),
        variable("missing", "u8", UnknownStorage("not live")),
    ), context)
    assert rows[0].result.value.value == 0x1234
    assert rows[1].result.value.value == 0x5678
    assert rows[1].result.warnings == ("register live range is not proven",)
    assert rows[2].result.value is None
    assert rows[2].result.unavailable_reason == "not live"
    assert context.reads == [(0x8000, 2)]
    assert context.validations == 1


def test_one_bad_variable_does_not_abort_table():
    context = Context(); evaluator = Evaluator(Project(()), ValueDecoder(), ValueLimits())
    rows = evaluator.evaluate_variables((
        variable("untyped", None, AbsoluteStorage(0x8000)),
        variable("good", "u8", AbsoluteStorage(0x8000)),
    ), context)
    assert rows[0].result.unavailable_reason == "variable has no known type"
    assert rows[1].result.value.value == 0x34


def test_isolated_cdb_variable_is_materialized_and_decoded():
    item = variable("counter", "u16", AbsoluteStorage(0x8000))
    project = Project((Image(image, variables=(item,)),))
    evaluator = Evaluator(project, ValueDecoder(), ValueLimits())
    request = ExpressionParser().parse_print(ExpandedTokens(tokenize("counter")))
    result = evaluator.evaluate_print(request, Context())
    assert result.kind == "variable"
    assert result.value.value == 0x1234


def test_cdb_variable_participates_by_value_in_arithmetic():
    item = variable("counter", "u16", AbsoluteStorage(0x8000))
    project = Project((Image(image, variables=(item,)),))
    evaluator = Evaluator(project, ValueDecoder(), ValueLimits())
    request = ExpressionParser().parse_print(ExpandedTokens(tokenize("counter+1")))
    result = evaluator.evaluate_print(request, Context())
    assert result.kind == "calculation"
    assert result.value.value == 0x1235
