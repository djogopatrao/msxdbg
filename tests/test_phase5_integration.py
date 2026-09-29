"""Phase 5 integrated command, session, rendering, and cleanup scenarios."""

from io import StringIO
import json

from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext
from msxdbg.debuginfo.sources import SourceRepository
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.values import ValueDecoder, ValueLimits
from msxdbg.session.core import Session
from msxdbg.session.state import SessionConfig
from msxdbg.target.api import RegisterSet
from msxdbg.target.fake import FakeTarget
from msxdbg.ui.application import CommandApplication
from msxdbg.ui.batch import BatchRunner
from msxdbg.ui.commands import (
    CommandContext, DisassemblyCursor, NavigationState, SourceCursor,
)


class Clock:
    def __init__(self): self.now = 0.0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


def integrated_context():
    project = Project(())
    target = FakeTarget(bytes(0x10000), RegisterSet({"PC": 0x100, "SP": 0xF000,
                                                     "IX": 0xE000, "A": 7}))
    session = Session(project, target, SessionConfig(), object(), Clock())
    session.attach()
    context = CommandContext(session, project, SourceRepository(), MacroCatalog(),
        MacroContext(), Evaluator(project, ValueDecoder(), ValueLimits()),
        NavigationState(SourceCursor(), DisassemblyCursor()), "batch")
    return context, target


def test_batch_end_to_end_breakpoint_step_queries_json_and_cleanup():
    context, target = integrated_context()
    output, errors = StringIO(), StringIO()
    commands = ("break 0x0200", "info breakpoints", "stepi", "where",
                "disassemble 0x0101 2", "info registers", "info pages")
    status = CommandApplication(batch=BatchRunner()).run_exec(
        commands, context, output, errors)
    lines = [json.loads(line) for line in output.getvalue().splitlines()]

    assert status == 0 and errors.getvalue() == ""
    assert [item["command"] for item in lines] == [
        "break", "info", "stepi", "where", "disassemble", "info", "info"]
    assert lines[0]["data"] == {
        "operation": "created",
        "breakpoint": {"number": 1, "address": 0x200, "status": "active",
                       "remote_id": "bp_id_0001", "location": None},
    }
    assert lines[1]["data"]["breakpoints"][0]["number"] == 1
    assert lines[2]["data"]["pc"] == 0x101
    assert lines[3]["data"]["stop_id"] == lines[2]["data"]["stop_id"]
    assert [item["text"] for item in lines[4]["data"]["instructions"]] == ["nop", "nop"]
    registers = {item["name"]: item["value"]
                 for item in lines[5]["data"]["registers"]}
    assert registers["PC"] == 0x101 and registers["A"] == 7
    assert len(lines[6]["data"]["pages"]) == 4
    operations = [call.operation for call in target.calls]
    assert "remove_breakpoint" in operations and operations[-1] == "close"


def test_batch_error_golden_stops_without_executing_later_commands():
    context, target = integrated_context()
    output, errors = StringIO(), StringIO()
    status = CommandApplication(batch=BatchRunner()).run_exec(
        ("print 2+3", "mode invalid", "stepi"), context, output, errors)
    lines = output.getvalue().splitlines()
    assert status == 1 and len(lines) == 2
    assert lines[0] == ('{"schema_version":1,"command_index":0,"command":"print",'
        '"ok":true,"data":{"kind":"calculation","display_base":10,"value":'
        '{"kind":"scalar","value":5,"type":"int","raw_bytes":""},'
        '"location":null,"unavailable_reason":null,"warnings":[]},'
        '"warnings":[],"error":null}')
    failed = json.loads(lines[1])
    assert failed == {
        "schema_version": 1, "command_index": 1, "command": "mode", "ok": False,
        "data": None, "warnings": [],
        "error": {"code": "invalid-arguments",
                  "message": "mode expects c, source, asm, or assembly",
                  "details": {}},
    }
    assert "step_into" not in [call.operation for call in target.calls]
