"""Phase 5 command parsing and registry contracts."""

import pytest

from msxdbg.debuginfo.model import ImageId
from msxdbg.ui.commands import (
    BreakpointNumberArguments, ConfirmationArguments, DisassembleArguments,
    ListArguments, ModeArguments, NoArguments, TargetArguments, build_registry,
    parse_target,
)


def test_parse_target_supports_all_documented_forms():
    assert parse_target("256").address == 0x100
    assert parse_target("0x9975").address == 0x9975
    assert parse_target("_Map_GetTile").symbol == "_Map_GetTile"
    source = parse_target("dll::libs/civ_font.c:603")
    assert source.image == ImageId("dll")
    assert (source.path, source.line) == ("libs/civ_font.c", 603)
    symbol = parse_target("resident::Map_GetTile")
    assert symbol.image == ImageId("resident") and symbol.symbol == "Map_GetTile"


@pytest.mark.parametrize("value", ("", "0x10000", "65536", "file.c:0",
                                   "::main", "app::", "a::b::c", "hl+1"))
def test_parse_target_rejects_invalid_or_expression_forms(value):
    with pytest.raises(ValueError):
        parse_target(value)


def test_registry_parsers_produce_typed_arguments():
    registry = build_registry()
    assert registry.lookup("break").parser("main")==TargetArguments(parse_target("main"))
    assert registry.lookup("delete").parser("2")==BreakpointNumberArguments(2)
    assert registry.lookup("continue").parser("")==NoArguments()
    assert registry.lookup("list").parser("next")==ListArguments(navigation="next")
    assert registry.lookup("list").parser("main.c:42")==ListArguments(path="main.c",line=42)
    assert registry.lookup("disas").parser("main 20")==DisassembleArguments(
        target=parse_target("main"), count=20)
    assert registry.lookup("mode").parser("source")==ModeArguments("c")
    assert registry.lookup("reset").parser("yes")==ConfirmationArguments(True)


@pytest.mark.parametrize(("command", "argument"), (
    ("delete", "bp#3"), ("step", "2"), ("until", ""),
    ("list", "main.c:0"), ("disassemble", "main 0"),
    ("mode", "machine"), ("reset", "YES"),
))
def test_registry_parsers_reject_unsupported_syntax(command, argument):
    with pytest.raises(ValueError):
        build_registry().lookup(command).parser(argument)
