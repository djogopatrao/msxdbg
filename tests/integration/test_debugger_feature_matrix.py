"""End-to-end coverage for every user-visible debugger command.

These tests deliberately cross the component boundaries that unit tests mock:
real SDCC/MSXgl artifacts are loaded, commands are parsed and dispatched, a
real Session talks to FakeTarget, and successful results are serialized using
the public JSON contract.
"""

from pathlib import Path
import json

import pytest

from msxdbg.debuginfo.loader import ImageSpec, ProjectLoader, ProjectSpec
from msxdbg.debuginfo.macros import MacroContext
from msxdbg.debuginfo.model import ImageId
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.values import ValueDecoder, ValueLimits
from msxdbg.session.core import Session
from msxdbg.session.safety import SafetyGate
from msxdbg.session.state import SessionConfig
from msxdbg.target.api import RegisterSet
from msxdbg.target.fake import FakeTarget
from msxdbg.ui.commands import (
    CommandContext,
    CommandDispatcher,
    DisassemblyCursor,
    NavigationState,
    SourceCursor,
    build_registry,
)
from msxdbg.ui.render_json import JsonRenderer


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "msxgl_debug"
OUT = FIXTURE / "out"


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def debugger(*, origin="interactive", pc=0x4065):
    loaded = ProjectLoader().load(ProjectSpec(
        (ImageSpec(ImageId("msxgl-debug"), OUT),), (FIXTURE,)))
    memory = bytearray(0x10000)
    memory[0x4000:0xC000] = (OUT / "debug_fixture.rom").read_bytes()
    target = FakeTarget(bytes(memory), RegisterSet({
        "PC": pc, "SP": 0xF000, "IX": 0xE000, "AF": 0x0700,
    }))
    clock = Clock()
    session = Session(loaded.project, target, SessionConfig(),
                      SafetyGate("integration"), clock)
    session.attach()
    context = CommandContext(
        session, loaded.project, loaded.sources, loaded.macros, MacroContext(),
        Evaluator(loaded.project, ValueDecoder(), ValueLimits()),
        NavigationState(SourceCursor(), DisassemblyCursor()), origin,
        execution_timeout=0.1,
    )
    return CommandDispatcher(), context, target


def dispatch_ok(dispatcher, context, command):
    result = dispatcher.dispatch(command, context)
    assert result.ok, (command, result.error)
    envelope = json.loads(JsonRenderer().encode(result, 0))
    assert envelope["schema_version"] == 1
    assert envelope["ok"] is True
    assert envelope["data"] is not None
    return result, envelope["data"]


EXPECTED_COMMANDS = {
    "break", "watch", "write", "delete", "suspend", "resume",
    "continue", "step", "next", "stepi", "finish", "where", "until",
    "backtrace", "frame", "list", "disassemble", "print", "info", "mode",
    "save", "reset", "load", "clear", "help", "quit",
}


def test_feature_inventory_covers_every_registered_command():
    """Keep this matrix failing when a command is added without integration coverage."""
    registered = {spec.name for spec in build_registry().specifications()}
    assert registered == EXPECTED_COMMANDS


def test_breakpoint_watchpoint_and_mutation_lifecycle():
    dispatcher, context, target = debugger()

    created, data = dispatch_ok(
        dispatcher, context, "break debug_fixture.c:17 if A == 7")
    assert data["breakpoint"]["address"] == 0x4065
    assert data["breakpoint"]["condition"] == "A == 7"
    _, suspended = dispatch_ok(dispatcher, context, "suspend 1")
    assert suspended["breakpoint"]["status"] == "suspended"
    assert suspended["breakpoint"]["remote_id"] is None
    assert target.list_breakpoints() == ()

    _, resumed = dispatch_ok(dispatcher, context, "resume 1")
    assert resumed["breakpoint"]["status"] == "active"
    assert resumed["breakpoint"]["remote_id"] != data["breakpoint"]["remote_id"]
    assert [point.address for point in target.list_breakpoints()] == [0x4065]

    _, watch = dispatch_ok(dispatcher, context, "watch access 0xc100 2")
    assert len(watch["breakpoint"]["remote_ids"]) == 2
    assert all(remote_id.startswith("wp_id_")
               for remote_id in watch["breakpoint"]["remote_ids"])
    assert {point.access for point in target.list_watchpoints()} == {"read", "write"}

    dispatch_ok(dispatcher, context, "write memory 0xc100 0x1234 u16 little")
    dispatch_ok(dispatcher, context, "write register A 0x2a")
    assert target.read_memory(0xC100, 2) == b"\x34\x12"
    assert context.session.where().snapshot.registers.get("A") == 0x2A

    _, table = dispatch_ok(dispatcher, context, "info breakpoints")
    assert [row["number"] for row in table["breakpoints"]] == [1, 2]
    dispatch_ok(dispatcher, context, "delete 1")
    dispatch_ok(dispatcher, context, "delete 2")
    assert context.session.breakpoints() == ()
    assert target.list_breakpoints() == ()
    assert target.list_watchpoints() == ()


@pytest.mark.parametrize(("command", "target_operation"), (
    ("continue", "continue_execution"),
    ("step", "step_into"),
    ("next", "step_over"),
    ("stepi", "step_into"),
    ("finish", "step_out"),
    ("until debug_fixture.c:17", "run_to"),
))
def test_every_execution_feature_reaches_the_target(command, target_operation):
    dispatcher, context, target = debugger(pc=0x405B)
    _, stop = dispatch_ok(dispatcher, context, command)
    assert stop["pc"] is not None
    assert target_operation in [call.operation for call in target.calls]
    if command == "until debug_fixture.c:17":
        run_to = next(call for call in target.calls if call.operation == "run_to")
        assert run_to.arguments == (0x4065,)
        assert stop["pc"] == 0x4065
    if command == "continue":
        assert "interrupt" in [call.operation for call in target.calls]


def test_source_disassembly_stack_and_expression_inspection_workflow():
    dispatcher, context, _ = debugger()

    _, where = dispatch_ok(dispatcher, context, "where")
    assert where["pc"] == 0x4065
    _, trace = dispatch_ok(dispatcher, context, "backtrace")
    assert trace["frames"][0]["function"] == "DebugTick"
    _, frame = dispatch_ok(dispatcher, context, "frame 0")
    assert frame["selected_index"] == 0

    _, source = dispatch_ok(dispatcher, context, "list debug_fixture.c:16")
    assert source["focal_line"] == 16
    dispatch_ok(dispatcher, context, "list next")
    dispatch_ok(dispatcher, context, "list previous")

    _, assembly = dispatch_ok(dispatcher, context, "disassemble 0x4065 2")
    assert len(assembly["instructions"]) == 2
    dispatch_ok(dispatcher, context, "disassemble next")
    dispatch_ok(dispatcher, context, "disassemble previous")

    _, value = dispatch_ok(dispatcher, context, "print 2 + 3")
    assert value["value"]["value"] == 5
    for command in (
        "info registers", "info pages", "info symbol 0x4056",
        "info locals", "info args", "info page3",
    ):
        dispatch_ok(dispatcher, context, command)


def test_modes_saved_state_safety_and_ui_commands():
    dispatcher, context, target = debugger()

    _, mode = dispatch_ok(dispatcher, context, "mode")
    assert mode["message"] == "source"
    _, mode = dispatch_ok(dispatcher, context, "mode asm")
    assert mode["message"] == "asm"

    dispatch_ok(dispatcher, context, "save")
    dispatch_ok(dispatcher, context, "write register PC 0x5000")
    dispatch_ok(dispatcher, context, "load yes")
    assert context.session.where().snapshot.registers.get("PC") == 0x4065
    dispatch_ok(dispatcher, context, "reset yes")
    assert "reset" in [call.operation for call in target.calls]

    _, clear = dispatch_ok(dispatcher, context, "clear")
    _, help_data = dispatch_ok(dispatcher, context, "help")
    _, quit_data = dispatch_ok(dispatcher, context, "quit")
    assert clear == {"action": "clear"}
    assert {entry["name"] for entry in help_data["commands"]} == EXPECTED_COMMANDS
    assert quit_data == {"action": "quit"}


@pytest.mark.parametrize("command", ("reset", "reset yes", "load", "load yes", "clear"))
def test_batch_forbidden_features_are_rejected_without_side_effects(command):
    """The batch policy is part of the debugger's safety feature set."""
    from io import StringIO

    from msxdbg.ui.batch import BatchRunner

    _, context, target = debugger(origin="batch")
    before = len(target.calls)
    output = StringIO()
    status = BatchRunner().run((command,), context, output)
    envelope = json.loads(output.getvalue())

    assert status == 1
    assert envelope["error"]["code"] == "command-not-available-in-batch"
    assert len(target.calls) == before
