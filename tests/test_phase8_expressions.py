from msxdbg.debuginfo.index import Project, SymbolContext
from msxdbg.debuginfo.model import (AbsoluteStorage, AddressRange, BlockScope,
    CodeLocation, Field, Function, FunctionId, Image, ImageId, ModuleId,
    RegisterStorage, Resolution, ResolutionStatus, StackStorage, TypeDef, TypeId,
    Variable, VariableId)
from msxdbg.eval.ast import AddressOf, Dereference, Index, Member, Name
from msxdbg.eval.evaluator import Evaluator, InvalidOperation
from msxdbg.eval.macros import ExpandedTokens
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext, parse_macro_definitions
from msxdbg.eval.service import EvaluationPipeline
from msxdbg.eval.parser import ExpressionParser
from msxdbg.eval.tokens import tokenize
from msxdbg.eval.values import AddressValue, StructValue, ValueDecoder, ValueLimits
from msxdbg.session.results import LocationResult
from msxdbg.session.frames import Frame, FrameService, FrameState
from msxdbg.target.api import RegisterSet


IMAGE = ImageId("app")
MODULE = ModuleId(IMAGE, "main")
POINT = TypeDef(TypeId("Point", IMAGE, MODULE), "Point", "struct", 3,
                fields=(Field("x", TypeId("u8"), 0),
                        Field("y", TypeId("i16"), 1)))
POINTS = TypeDef(TypeId("Point[2]", IMAGE, MODULE), "Point[2]", "array", 6,
                 referenced_type=POINT.id, array_count=2)
POINT_PTR = TypeDef(TypeId("Point*", IMAGE, MODULE), "Point*", "pointer", 2,
                    False, POINT.id)


def variable(name, type_, address):
    return Variable(VariableId(MODULE, name), name, None, None, type_.id,
                    AbsoluteStorage(address))


VARIABLES = (
    variable("point", POINT, 0x100),
    variable("points", POINTS, 0x110),
    variable("p", POINT_PTR, 0x120),
)
PROJECT = Project((Image(IMAGE, variables=VARIABLES,
                         types=(POINT, POINTS, POINT_PTR)),))


class Context:
    signature_status = "verified"
    registers = RegisterSet({"PC": 0x8000})
    symbol_context = SymbolContext(IMAGE, MODULE, None, 0x8000)
    def __init__(self):
        self.memory = bytearray(0x10000); self.reads = []
        self.memory[0x100:0x103] = bytes((7, 0x34, 0x12))
        self.memory[0x110:0x116] = bytes((1, 2, 0, 9, 0xFE, 0xFF))
        self.memory[0x120:0x122] = bytes((0x00, 0x01))
    def locate_variable(self, item): return LocationResult(address=item.storage.address)
    def read_memory(self, address, size):
        self.reads.append((address, size)); return bytes(self.memory[address:address+size])
    def validate(self): pass


def request(text):
    return ExpressionParser().parse_print(ExpandedTokens(tokenize(text)))


def subject(): return Evaluator(PROJECT, ValueDecoder(), ValueLimits())


def test_parser_builds_c_typed_operator_ast_with_postfix_precedence():
    parser = ExpressionParser()
    assert parser.parse_expression("&point") == AddressOf(Name("point"))
    assert parser.parse_expression("*p") == Dereference(Name("p"))
    assert parser.parse_expression("points[1].x") == Member(Index(Name("points"),
        parser.parse_expression("1")), "x")
    assert parser.parse_expression("p->y") == Member(Name("p"), "y", True)


def test_address_of_does_not_read_and_member_uses_proven_offset():
    context = Context()
    address = subject().evaluate_print(request("&point"), context)
    assert isinstance(address.value, AddressValue) and address.value.address == 0x100
    assert context.reads == []
    field = subject().evaluate_print(request("point.y"), context)
    assert field.value.value == 0x1234
    assert field.location.address == 0x101
    assert context.reads == [(0x101, 2)]


def test_array_index_scales_by_element_and_can_select_nested_field():
    context = Context()
    result = subject().evaluate_print(request("points[1].y"), context)
    assert result.value.value == -2
    assert result.location.address == 0x114
    assert context.reads == [(0x114, 2)]


def test_pointer_dereference_and_arrow_read_pointer_as_z80_u16():
    context = Context()
    result = subject().evaluate_print(request("p->x"), context)
    assert result.value.value == 7
    assert context.reads == [(0x120, 2), (0x100, 1)]
    context = Context()
    whole = subject().evaluate_print(request("*p"), context)
    assert isinstance(whole.value, StructValue)
    assert context.reads == [(0x120, 2), (0x100, 3)]


def test_typed_errors_are_explicit():
    context = Context()
    for expression in ("point.missing", "point->x", "points[2]"):
        try:
            subject().evaluate_print(request(expression), context)
        except InvalidOperation:
            pass
        else:
            raise AssertionError(expression + " unexpectedly succeeded")


def test_header_macros_expand_into_typed_operators_before_parsing(tmp_path):
    parsed = parse_macro_definitions(
        "#define FIELD(p) ((p)->y)\n#define ELEMENT(a,i) ((a)[i].x)\n",
        tmp_path / "types.h", MacroContext())
    assert parsed.diagnostics == ()
    pipeline = EvaluationPipeline(PROJECT, subject())
    context = Context()
    field = pipeline.evaluate_print("FIELD(p)", MacroCatalog(parsed.value),
                                    MacroContext(), lambda: context)
    element = pipeline.evaluate_print("ELEMENT(points,1)", MacroCatalog(parsed.value),
                                      MacroContext(), lambda: context)
    assert field.value.value == 0x1234
    assert element.value.value == 9


def test_typed_member_arithmetic_materializes_only_selected_field():
    context = Context()
    result = subject().evaluate_print(request("point.y + points[1].x"), context)
    assert result.value.value == 0x123D
    assert context.reads == [(0x101, 2), (0x113, 1)]


FUNCTION_ID = FunctionId(MODULE, "inspect")
FUNCTION = Function(FUNCTION_ID, "inspect", 0x8000, 0x8020,
    locations=(CodeLocation(IMAGE, 0x8004, MODULE, function=FUNCTION_ID),),
    scopes=(BlockScope(1, 0, 1, AddressRange(0x8004, 0x8020)),))


def scoped_variable(name, storage, function=None, scope="global"):
    return Variable(VariableId(MODULE, name), name, function,
        1 if function else None, POINT.id, storage, scope=scope, level=1 if function else None)


SCOPED_VARIABLES = (
    scoped_variable("local_point", StackStorage(-3), FUNCTION_ID, "local"),
    scoped_variable("register_point", RegisterStorage(("L", "H", "A")), FUNCTION_ID, "local"),
    scoped_variable("static_point", AbsoluteStorage(0x300), scope="static"),
    scoped_variable("global_point", AbsoluteStorage(0x310)),
)
SCOPED_PROJECT = Project((Image(IMAGE, functions=(FUNCTION,),
    variables=SCOPED_VARIABLES, types=(POINT,)),))


class ScopedContext:
    signature_status = "verified"
    symbol_context = SymbolContext(IMAGE, MODULE, FUNCTION_ID, 0x8008)
    def __init__(self, frame_index=0):
        self.frame = Frame(frame_index, 0x8008, 0x8008,
            Resolution(ResolutionStatus.UNIQUE, (FUNCTION,)), 0x9000,
            FrameState.IX_ACTIVE)
        self.registers = RegisterSet({"L": 1, "H": 2, "A": 3})
        self.memory = bytearray(0x10000)
        self.memory[0x8FFD:0x9000] = bytes((4, 0x78, 0x56))
        self.memory[0x300:0x303] = bytes((5, 0x34, 0x12))
        self.memory[0x310:0x313] = bytes((6, 0xCD, 0xAB))
        self.service = FrameService()
    def locate_variable(self, item):
        return self.service.locate(item, self.frame, self.registers, self)
    def read_memory(self, address, size):
        return bytes(self.memory[address:address + size])
    def validate(self): pass


def test_typed_fields_resolve_in_current_frame_static_and_global_scope():
    evaluator = Evaluator(SCOPED_PROJECT, ValueDecoder(), ValueLimits())
    context = ScopedContext()
    assert evaluator.evaluate_print(request("local_point.y"), context).value.value == 0x5678
    assert evaluator.evaluate_print(request("static_point.y"), context).value.value == 0x1234
    assert evaluator.evaluate_print(request("global_point.y"), context).value.value == -0x5433


def test_caller_frame_keeps_stack_lvalues_but_rejects_register_lvalues():
    evaluator = Evaluator(SCOPED_PROJECT, ValueDecoder(), ValueLimits())
    context = ScopedContext(frame_index=1)
    assert evaluator.evaluate_print(request("local_point.x"), context).value.value == 4
    try:
        evaluator.evaluate_print(request("register_point.x"), context)
    except InvalidOperation as error:
        assert "caller frames" in str(error)
    else:
        raise AssertionError("caller register storage unexpectedly materialized")


def test_address_of_rejects_register_backed_lvalue_without_reading_it():
    evaluator = Evaluator(SCOPED_PROJECT, ValueDecoder(), ValueLimits())
    try:
        evaluator.evaluate_print(request("&register_point"), ScopedContext())
    except InvalidOperation as error:
        assert "memory-backed" in str(error)
    else:
        raise AssertionError("register lvalue unexpectedly acquired an address")
