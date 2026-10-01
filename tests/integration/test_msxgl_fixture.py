"""Integration tests using artifacts emitted by the real MSXgl/SDCC toolchain."""

from pathlib import Path

from msxdbg.debuginfo.macros import MacroContext
from msxdbg.debuginfo.loader import ImageSpec, ProjectLoader, ProjectSpec
from msxdbg.debuginfo.model import ImageId
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.values import ValueDecoder, ValueLimits
from msxdbg.session.core import Session
from msxdbg.session.results import TargetQuery
from msxdbg.session.safety import SafetyGate
from msxdbg.session.state import SessionConfig, SessionState
from msxdbg.target.api import RegisterSet
from msxdbg.target.fake import FakeTarget
from msxdbg.ui.commands import (CommandContext, CommandDispatcher,
    DisassemblyCursor, NavigationState, SourceCursor)


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "msxgl_debug"
OUT = FIXTURE / "out"


class Clock:
    def monotonic(self): return 0.0
    def sleep(self, seconds): return None


def load_fixture():
    spec = ProjectSpec((ImageSpec(ImageId("msxgl-debug"), OUT),), (FIXTURE,))
    return ProjectLoader().load(spec)


def integrated_fixture_context(pc=0x4065):
    loaded = load_fixture()
    rom = (OUT / "debug_fixture.rom").read_bytes()
    memory = bytearray(0x10000)
    memory[0x4000:0xC000] = rom
    target = FakeTarget(bytes(memory), RegisterSet({
        "PC": pc, "SP": 0xF000, "IX": 0xE000,
    }))
    session = Session(loaded.project, target, SessionConfig(), SafetyGate(), Clock())
    session.attach()
    context = CommandContext(
        session, loaded.project, loaded.sources, loaded.macros, MacroContext(),
        Evaluator(loaded.project, ValueDecoder(), ValueLimits()),
        NavigationState(SourceCursor(), DisassemblyCursor()), "batch",
    )
    return context, target


def test_real_msxgl_artifacts_resolve_functions_lines_and_variables():
    loaded = load_fixture()
    project = loaded.project

    functions = {item.name: item for item in project.images[0].functions}
    assert set(functions) == {"AddThree", "DebugTick", "main"}
    assert (functions["AddThree"].entry, functions["AddThree"].end) == (
        0x4056, 0x405B)
    assert project.resolve_line("debug_fixture.c", 17).unique_or_none().location.address == 0x4065
    assert project.lookup_symbol("g_DebugCounter").unique_or_none().address == 0xC003
    assert {item.name for item in project.images[0].variables} == {
        "value", "local", "g_DebugCounter", "g_DebugDone"}


def test_real_rom_drives_source_breakpoint_and_backtrace_session_flow():
    loaded = load_fixture()
    rom = (OUT / "debug_fixture.rom").read_bytes()
    assert len(rom) == 0x8000 and rom[:2] == b"AB"
    memory = bytearray(0x10000)
    memory[0x4000:0xC000] = rom
    target = FakeTarget(bytes(memory), RegisterSet({
        "PC": 0x405B, "SP": 0xF000, "IX": 0xE000,
    }))
    session = Session(loaded.project, target, SessionConfig(), SafetyGate(), Clock())

    assert session.attach() == SessionState.STOPPED
    resolution = session.resolve_target(TargetQuery(
        path="debug_fixture.c", line=17))
    breakpoint = session.add_breakpoint(resolution.unique_or_none())
    assert breakpoint.address == 0x4065
    assert breakpoint.location.source.line == 17
    assert target.list_breakpoints()[0].address == 0x4065

    trace = session.backtrace()
    assert trace.frames[0].function.unique_or_none().name == "DebugTick"
    assert trace.termination_reason == "current-frame-not-active"


def test_issue_3_list_preserves_requested_line_and_uses_current_location():
    context, _ = integrated_fixture_context()
    dispatcher = CommandDispatcher()

    requested = dispatcher.dispatch("list debug_fixture.c:16", context)
    current = dispatcher.dispatch("list", context)

    assert requested.ok and requested.payload.window.focal_line == 16
    assert dict(requested.payload.window.lines)[16] == "\tg_DebugCounter = AddThree(g_DebugCounter);"
    assert current.ok and current.payload.window.focal_line == 17
    assert current.payload.window.path.name == "debug_fixture.c"


def test_issue_4_info_breakpoints_keeps_compiled_source_location():
    context, target = integrated_fixture_context()
    dispatcher = CommandDispatcher()

    created = dispatcher.dispatch("break debug_fixture.c:17", context)
    listed = dispatcher.dispatch("info breakpoints", context)

    assert created.ok and listed.ok
    record = listed.payload.records[0]
    assert record.address == 0x4065
    assert record.location.source.path.endswith("debug_fixture.c")
    assert record.location.source.line == 17
    assert target.list_breakpoints()[0].address == 0x4065


def test_issue_7_external_stop_is_reconciled_with_real_msxgl_debug_info():
    context, _ = integrated_fixture_context()
    context.session.invalidate()

    trace = context.session.backtrace()

    assert context.session.state == SessionState.STOPPED
    assert trace.frames[0].function.unique_or_none().name == "DebugTick"
