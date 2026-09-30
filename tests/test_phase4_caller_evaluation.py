"""Selected-caller evaluation using storage records parsed from a CDB fixture."""

from __future__ import annotations

from pathlib import Path

import pytest

from msxdbg.debuginfo.cdb_parser import parse_cdb
from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext
from msxdbg.debuginfo.model import (
    AddressRange,
    BlockScope,
    CodeLocation,
    Function,
    FunctionId,
    Image,
    ImageId,
    ModuleId,
    RegisterStorage,
    SourceSpan,
    StackStorage,
    TypeId,
    Variable,
    VariableId,
)
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.values import ValueDecoder, ValueLimits
from msxdbg.session.core import Session
from msxdbg.session.state import SessionConfig
from msxdbg.target.api import RegisterSet
from msxdbg.ui.commands import (
    CommandContext,
    CommandDispatcher,
    DisassemblyCursor,
    NavigationState,
    SourceCursor,
)
from test_phase4_frame_contracts import Clock, FrameTarget, FixtureReader, cpu_fixture


CDB_FIXTURE = Path(__file__).parent / "fixtures" / "cpu" / "frame_locals.cdb"


@pytest.fixture
def caller_context(cpu_fixture):
    parsed = parse_cdb(
        CDB_FIXTURE.read_text(encoding="utf-8").splitlines(), CDB_FIXTURE
    )
    assert parsed.diagnostics == ()

    image_id = ImageId("phase4")
    module = ModuleId(image_id, "frames")
    functions = []
    for spec in cpu_fixture["functions"]:
        function_id = FunctionId(module, spec["name"])
        locations = (
            CodeLocation(
                image_id,
                spec["entry"],
                module=module,
                function=function_id,
                source=SourceSpan("frames.c", "frames.c", 10),
            ),
        )
        scopes = ((BlockScope(1, 0, 3, AddressRange(spec["entry"], spec["end"])),)
                  if spec["name"] == "middle" else ())
        functions.append(Function(
            function_id, spec["name"], spec["entry"], spec["end"],
            locations=locations, scopes=scopes,
        ))

    middle = next(item for item in functions if item.name == "middle")
    variables = []
    for raw in parsed.value.symbols:
        if raw.storage.code == "B":
            storage = StackStorage(raw.storage.offset)
        else:
            storage = RegisterStorage(tuple(raw.storage.registers))
        variables.append(Variable(
            VariableId(module, raw.identity.raw), raw.identity.name, middle.id,
            raw.identity.block, TypeId("u16"), storage,
            is_parameter=raw.identity.name == "arg",
            scope="local", level=raw.identity.level,
            sublevel=raw.identity.sublevel, evidence=(raw.origin,),
        ))

    project = Project((Image(
        image_id, functions=tuple(functions), variables=tuple(variables)
    ),))
    reader = FixtureReader(cpu_fixture)
    caller_ix = cpu_fixture["frame_chains"]["three_frames"][1]["ix"]
    reader.memory[caller_ix - 2 : caller_ix] = b"\x34\x12"
    reader.memory[caller_ix + 4 : caller_ix + 6] = b"\x78\x56"
    target = FrameTarget(reader, RegisterSet({
        **cpu_fixture["registers"], "HL": 0x9999,
    }))
    session = Session(project, target, SessionConfig(), object(), Clock())
    session.attach()
    session.select_frame(1)
    evaluator = Evaluator(project, ValueDecoder(), ValueLimits())
    context = CommandContext(
        session, project, object(), MacroCatalog(), MacroContext(), evaluator,
        NavigationState(SourceCursor(), DisassemblyCursor()), "interactive",
    )
    return context


def test_info_locals_and_args_use_selected_caller_cdb_storage(caller_context):
    dispatcher = CommandDispatcher()
    locals_result = dispatcher.dispatch("info locals", caller_context)
    args_result = dispatcher.dispatch("info args", caller_context)

    assert locals_result.ok and args_result.ok
    locals_by_name = {row.variable.name: row.result for row in locals_result.payload}
    assert locals_by_name["local"].value.value == 0x1234
    assert locals_by_name["reglocal"].unavailable_reason == (
        "register storage is unavailable in caller frames"
    )
    assert [(row.variable.name, row.result.value.value) for row in args_result.payload] == [
        ("arg", 0x5678)
    ]


def test_print_reads_cdb_local_and_argument_from_selected_caller(caller_context):
    dispatcher = CommandDispatcher()
    assert dispatcher.dispatch("print local", caller_context).payload.value.value == 0x1234
    assert dispatcher.dispatch("print local + 1", caller_context).payload.value.value == 0x1235
    assert dispatcher.dispatch("print arg", caller_context).payload.value.value == 0x5678


def test_print_does_not_use_live_register_for_caller_local(caller_context):
    result = CommandDispatcher().dispatch("print reglocal", caller_context)
    assert result.ok
    assert result.payload.unavailable_reason == (
        "register storage is unavailable in caller frames"
    )
