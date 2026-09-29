"""Phase 4 command, text, and JSON presentation scenarios."""

from __future__ import annotations

import json
from types import SimpleNamespace

from msxdbg.ui.commands import CommandDispatcher
from msxdbg.ui.render_json import JsonRenderer
from msxdbg.ui.render_text import TextRenderer
from test_phase4_frame_contracts import cpu_fixture, make_session


class Console:
    def __init__(self):
        self.lines = []

    def print(self, *objects):
        self.lines.append(" ".join(map(str, objects)))


def context_for(data):
    session, target = make_session(data)
    session.attach()
    return SimpleNamespace(session=session), target


def test_dispatches_backtrace_alias_and_frame_selection(cpu_fixture):
    context, _ = context_for(cpu_fixture)
    dispatcher = CommandDispatcher()

    trace = dispatcher.dispatch("bt", context)
    assert trace.ok
    assert trace.command == "backtrace"
    assert len(trace.payload.frames) == 3
    assert trace.payload.selected_index == 0

    selected = dispatcher.dispatch("frame 1", context)
    assert selected.ok
    assert selected.payload.frames[0].index == 1
    assert selected.payload.selected_index == 1
    assert dispatcher.dispatch("frame", context).payload.frames[0].index == 1


def test_frame_command_reports_argument_and_session_errors(cpu_fixture):
    context, _ = context_for(cpu_fixture)
    dispatcher = CommandDispatcher()

    assert dispatcher.dispatch("backtrace extra", context).error.code == "invalid-arguments"
    assert dispatcher.dispatch("frame -1", context).error.code == "invalid-arguments"
    assert dispatcher.dispatch("frame 99", context).error.code == "invalid-arguments"

    detached, _ = make_session(cpu_fixture)
    failed = dispatcher.dispatch("backtrace", SimpleNamespace(session=detached))
    assert failed.error.code == "session"
    assert failed.error.details["error_type"] == "InvalidSessionState"


def test_text_renderer_marks_selection_and_reports_termination(cpu_fixture):
    context, _ = context_for(cpu_fixture)
    context.session.select_frame(1)
    result = CommandDispatcher().dispatch("backtrace", context)
    console = Console()
    TextRenderer().render(result, console)

    assert console.lines[0] == " #0  0x1108 in leaf ()"
    assert console.lines[1] == "*#1  0x1211 in middle ()"
    assert console.lines[2] == " #2  0x1311 in root ()"
    assert console.lines[3] == "<backtrace stopped: invalid-return-address>"


def test_json_renderer_emits_structured_frames(cpu_fixture):
    context, _ = context_for(cpu_fixture)
    context.session.select_frame(1)
    result = CommandDispatcher().dispatch("backtrace", context)
    payload = json.loads(JsonRenderer().encode(result, 4))["data"]

    assert payload["selected_index"] == 1
    assert payload["termination_reason"] == "invalid-return-address"
    assert payload["frames"][1] == {
        "index": 1,
        "selected": True,
        "pc": 0x1211,
        "scope_pc": 0x1210,
        "ix": 0x9020,
        "state": "ix-active",
        "function_status": "unique",
        "function": "middle",
    }
