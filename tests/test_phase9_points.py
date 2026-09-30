import pytest

from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import (AbsoluteStorage, Image, ImageId, ModuleId,
    TypeId, Variable, VariableId)
from msxdbg.session.breakpoints import BreakpointManager, BreakpointStatus
from msxdbg.session.breakpoints import MappingQualifier
from msxdbg.session.conditions import (ConditionCompiler, ConditionSyntaxError,
                                       compile_mapping_qualifier)
from msxdbg.target.api import RegisterSet
from msxdbg.target.fake import FakeTarget
from msxdbg.ui.commands import BreakArguments, WatchArguments, build_registry, parse_target


IMAGE=ImageId("app"); MODULE=ModuleId(IMAGE,"main")
COUNTER=Variable(VariableId(MODULE,"counter"),"counter",None,None,
                 TypeId("u16"),AbsoluteStorage(0xC000))
PROJECT=Project((Image(IMAGE,variables=(COUNTER,)),))


def target(): return FakeTarget(bytes(0x10000),RegisterSet({"PC":0}))


def test_condition_compiler_accepts_only_generated_predicate_grammar():
    result=ConditionCompiler(PROJECT).compile("counter == 3 && A != 0")
    assert result.source == "counter == 3 && A != 0"
    assert "[debug read memory 49152]" in result.tcl_expression
    assert "[reg A]" in result.tcl_expression
    for unsafe in ("exec foo", "A; reset", "[debug break]", "$x", "A { 1"):
        with pytest.raises(ConditionSyntaxError):
            ConditionCompiler(PROJECT).compile(unsafe)


def test_approved_break_and_watch_syntax_parses_to_typed_arguments():
    registry=build_registry()
    assert registry.lookup("break").parser("main if A == 1") == \
        BreakArguments(parse_target("main"),"A == 1")
    assert registry.lookup("watch").parser("access 0xC000 2") == \
        WatchArguments("access",parse_target("0xC000"),2)


def test_mapping_qualified_break_syntax_and_generated_predicate():
    arguments=build_registry().lookup("break").parser(
        "0x8000 if A == 3 page 2 slot 3.2 segment 7")
    assert arguments == BreakArguments(parse_target("0x8000"),"A == 3",
        MappingQualifier(2,3,2,7))
    generated=compile_mapping_qualifier(arguments.qualifier)
    assert "get_selected_slot 2" in generated
    assert "MapperIO 2" in generated
    assert "3" in generated and "7" in generated


@pytest.mark.parametrize("text",(
    "0x8000 page 4", "0x8000 slot 4", "0x8000 slot 2.4",
    "0x8000 segment 2", "0x8000 page 2 page 3"))
def test_invalid_mapping_qualifiers_fail_before_creation(text):
    with pytest.raises(ValueError): build_registry().lookup("break").parser(text)


def test_access_watchpoint_has_one_local_identity_and_two_remote_ids():
    remote=target(); manager=BreakpointManager(remote)
    record=manager.create_watchpoint("access",0xC000,2)
    assert record.number == 1 and record.kind == "watchpoint"
    assert record.access == "access" and len(record.remote_ids) == 2
    assert {item.access for item in remote.list_watchpoints()} == {"read","write"}
    suspended=manager.suspend(1)
    assert suspended.status == BreakpointStatus.SUSPENDED
    assert remote.list_watchpoints() == ()
    resumed=manager.resume(1)
    assert resumed.number == 1 and len(resumed.remote_ids) == 2


def test_watchpoint_range_is_validated_before_remote_mutation():
    remote=target(); manager=BreakpointManager(remote)
    with pytest.raises(ValueError,match="outside CPU memory"):
        manager.create_watchpoint("write",0xFFFF,2)
    assert not any(call.operation == "create_watchpoint" for call in remote.calls)
