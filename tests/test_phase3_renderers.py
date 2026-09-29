"""Text and JSON rendering for evaluation payloads."""
import json
from pathlib import Path
import pytest
from msxdbg.debuginfo.model import AbsoluteStorage, ImageId, ModuleId, TypeId, Variable, VariableId
from msxdbg.debuginfo.model import Resolution, ResolutionStatus
from msxdbg.debuginfo.sources import SourceWindow
from msxdbg.eval.values import (ArrayValue, ScalarValue, StringValue, StructValue,
    ValueResult, VariableRow)
from msxdbg.session.breakpoints import BreakpointRecord
from msxdbg.session.results import DisassemblyResult, LocationResult, StopResult
from msxdbg.session.state import StopSnapshot
from msxdbg.target.api import Instruction, PageState, RegisterSet
from msxdbg.ui.render_json import JsonRenderer
from msxdbg.ui.render_text import TextRenderer
from msxdbg.ui.results import (BreakpointPayload, BreakpointTable, CommandError,
    CommandResult, DisassemblyPayload, HelpPayload, MessagePayload, PageTable,
    RegisterTable, SourcePayload, StopPayload, UiAction)

class Console:
    def __init__(self): self.lines=[]
    def print(self,*objects): self.lines.append(" ".join(map(str,objects)))

def scalar(value, base=10, kind="calculation", location=None):
    return ValueResult(ScalarValue(value,TypeId("int"),b""),kind,base,location)

def render(payload):
    console=Console(); TextRenderer().render(CommandResult("print",True,payload),console); return console.lines

def test_text_formats_decimal_hex_binary_and_negative_values():
    assert render(scalar(15)) == ["15"]
    assert render(scalar(255,16)) == ["0xff"]
    assert render(scalar(-10,16)) == ["-0xa"]
    assert render(scalar(10,2)) == ["0b1010"]

def test_text_distinguishes_memory_strings_arrays_and_structs():
    memory=scalar(0x1234,10,"memory",LocationResult(address=0x8000))
    assert render(memory)==["0x8000: 4660"]
    assert render(ValueResult(StringValue("olá",True,False,b"ol\xe1\0"),"memory",10)) == ["'olá'"]
    array=ArrayValue((ScalarValue(1,TypeId("u8"),b"\1"),),True)
    assert render(ValueResult(array,"memory",10)) == ["[1, …]"]
    struct=StructValue((("x",ScalarValue(2,TypeId("u8"),b"\2")),))
    assert render(ValueResult(struct,"memory",10)) == ["{x=2}"]

def test_text_renders_variable_rows_unavailability_and_escapes_markup():
    module=ModuleId(ImageId("app"),"main")
    variable=Variable(VariableId(module,"bad"),"name[tag]",None,None,TypeId("u8"),AbsoluteStorage(0))
    location=LocationResult(unavailable_reason="not [live]")
    result=ValueResult(None,"variable",10,location,"not [live]")
    assert render((VariableRow(variable,location,result),)) == ["name\\[tag] = <unavailable: not \\[live]>"]

def test_json_preserves_large_integer_bytes_and_schema():
    payload=ValueResult(ScalarValue(10**40,TypeId("u64"),b"\x01\xff"),"calculation",10)
    encoded=JsonRenderer().encode(CommandResult("print",True,payload),7)
    assert "\n" not in encoded
    data=json.loads(encoded)
    assert data["schema_version"]==1 and data["command_index"]==7 and data["ok"]
    assert data["data"]["value"]["value"]==10**40
    assert data["data"]["value"]["raw_bytes"]=="01ff"
    assert data["error"] is None

def test_json_nonfinite_classification_and_error_envelope():
    special=ScalarValue({"value":None,"classification":"+infinity"},TypeId("f32"),b"\0\0\x80\x7f")
    data=json.loads(JsonRenderer().encode(CommandResult("print",True,ValueResult(special,"calculation",10)),0))
    assert data["data"]["value"]["value"]["classification"]=="+infinity"
    failed=CommandResult("print",False,error=CommandError("bad","failed",{"start":2}))
    error=json.loads(JsonRenderer().encode(failed,1))
    assert error["error"]=={"code":"bad","message":"failed","details":{"start":2}}
    assert error["data"] is None and error["warnings"] == []


def test_json_explicitly_maps_session_and_navigation_payloads():
    record = BreakpointRecord(2, 0x1234, None, "bp#2", "active")
    registers = RegisterSet({"PC": 0x1234, "A": 7})
    snapshot = StopSnapshot(3, 1, registers,
        Resolution(ResolutionStatus.MISSING), "verified")
    payloads = (
        (BreakpointPayload(record, "created"), "breakpoint"),
        (BreakpointTable((record,)), "breakpoints"),
        (RegisterTable(registers), "registers"),
        (PageTable((PageState(0, "0", "0", "3"),)), "pages"),
        (SourcePayload(SourceWindow(Path("main.c"), ((1, "int main(void)"),), 1)), "lines"),
        (DisassemblyPayload(DisassemblyResult(
            (Instruction(0x1234, 1, "nop", b"\0"),),
            (Resolution(ResolutionStatus.MISSING),), 0x1234, 0x1235)), "instructions"),
        (StopPayload(StopResult(snapshot)), "stop_id"),
        (MessagePayload("saved"), "message"),
        (HelpPayload((("help", "help", "Show help"),)), "commands"),
        (UiAction(UiAction.CLEAR), "action"),
    )
    renderer = JsonRenderer()
    for payload, key in payloads:
        data = json.loads(renderer.encode(CommandResult("test", True, payload), 0))["data"]
        assert key in data


def test_renderers_reject_unknown_payload_instead_of_leaking_internals():
    result = CommandResult("bad", True, object())
    with pytest.raises(TypeError, match="unsupported command payload"):
        JsonRenderer().encode(result, 0)
    with pytest.raises(TypeError, match="unsupported command payload"):
        TextRenderer().render(result, Console())
