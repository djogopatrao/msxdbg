"""Phase 4 integration through discovery, parsing, reconciliation and session/UI."""

from __future__ import annotations

from pathlib import Path

from msxdbg.debuginfo.index import SymbolContext, VariableKind
from msxdbg.debuginfo.loader import ImageSpec, ProjectLoader, ProjectSpec
from msxdbg.debuginfo.macros import MacroContext
from msxdbg.debuginfo.model import ImageId, RegisterStorage, StackStorage
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


FIXTURES = Path(__file__).parent / "fixtures" / "cpu"


def load_phase4_project():
    spec = ImageSpec(
        ImageId("phase4"), FIXTURES,
        maps=(FIXTURES / "frame_loader.map",),
        cdbs=(FIXTURES / "frame_locals.cdb",),
    )
    return ProjectLoader().load(ProjectSpec((spec,)))


def test_loader_reconciles_phase4_functions_scopes_and_storage():
    loaded = load_phase4_project()
    project = loaded.project
    assert not [item for item in loaded.diagnostics if item.severity == "error"]

    middle = project.function_at(0x1210).unique_or_none()
    assert middle is not None
    assert (middle.name, middle.entry, middle.end) == ("middle", 0x1200, 0x1220)
    assert [(scope.block, scope.extent.start, scope.extent.end_exclusive)
            for scope in middle.scopes] == [(3, 0x1208, 0x1211)]

    context = SymbolContext(ImageId("phase4"), middle.id.module, middle.id, 0x1210)
    locals_ = project.variables_in_scope(context, VariableKind.LOCALS)
    arguments = project.variables_in_scope(context, VariableKind.PARAMETERS)
    assert {item.name for item in locals_} == {"local", "reglocal"}
    assert [item.name for item in arguments] == ["arg"]
    assert isinstance(project.find_variable("local", context).unique_or_none().storage,
                      StackStorage)
    assert isinstance(project.find_variable("reglocal", context).unique_or_none().storage,
                      RegisterStorage)


def test_loaded_project_drives_backtrace_locals_args_and_print(cpu_fixture):
    loaded = load_phase4_project()
    reader = FixtureReader(cpu_fixture)
    caller_ix = cpu_fixture["frame_chains"]["three_frames"][1]["ix"]
    reader.memory[caller_ix - 2 : caller_ix] = b"\x34\x12"
    reader.memory[caller_ix + 4 : caller_ix + 6] = b"\x78\x56"
    target = FrameTarget(reader, RegisterSet({
        **cpu_fixture["registers"], "HL": 0x9999,
    }))
    session = Session(loaded.project, target, SessionConfig(), object(), Clock())
    session.attach()
    session.select_frame(1)
    evaluator = Evaluator(loaded.project, ValueDecoder(), ValueLimits())
    command_context = CommandContext(
        session, loaded.project, loaded.sources, loaded.macros, MacroContext(),
        evaluator, NavigationState(SourceCursor(), DisassemblyCursor()), "interactive",
    )
    dispatcher = CommandDispatcher()

    trace = dispatcher.dispatch("backtrace", command_context)
    assert trace.ok
    assert [frame.function.unique_or_none().name for frame in trace.payload.frames] == [
        "leaf", "middle", "root"
    ]
    assert trace.payload.selected_index == 1

    locals_result = dispatcher.dispatch("info locals", command_context)
    args_result = dispatcher.dispatch("info args", command_context)
    locals_by_name = {row.variable.name: row.result for row in locals_result.payload}
    assert locals_by_name["local"].value.value == 0x1234
    assert locals_by_name["reglocal"].unavailable_reason == (
        "register storage is unavailable in caller frames"
    )
    assert args_result.payload[0].result.value.value == 0x5678
    assert dispatcher.dispatch("print local + arg", command_context).payload.value.value == 0x68AC
