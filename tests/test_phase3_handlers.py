"""Presentation-neutral handlers for Phase 3 evaluation commands."""

from pathlib import Path

from msxdbg.debuginfo.diagnostics import Origin
from msxdbg.debuginfo.index import Project, SymbolContext
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext, MacroDefinition, MacroToken
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.values import ValueDecoder, ValueLimits
from msxdbg.target.api import RegisterSet
from msxdbg.ui.commands import (CommandContext, DisassemblyCursor, InfoArguments,
    NavigationState, PrintArguments, SourceCursor, handle_info, handle_print)


class Inspection:
    registers = RegisterSet({"PC": 0x1234})
    symbol_context = SymbolContext(None, None, None, 0x1234)
    def validate(self): pass


class Session:
    def __init__(self): self.calls = 0; self.context = Inspection()
    def inspection(self): self.calls += 1; return self.context


def command_context(macros=MacroCatalog()):
    project = Project(())
    session = Session()
    context = CommandContext(session, project, object(), macros, MacroContext(),
        Evaluator(project, ValueDecoder(), ValueLimits()),
        NavigationState(SourceCursor(), DisassemblyCursor()), "interactive")
    return context, session


def test_print_constant_returns_payload_without_inspection():
    context, session = command_context()
    result = handle_print(PrintArguments("2+3*4"), context)
    assert result.ok
    assert result.payload.value.value == 14
    assert session.calls == 0


def test_print_live_register_obtains_one_inspection():
    context, session = command_context()
    result = handle_print(PrintArguments("PC+1"), context)
    assert result.ok
    assert result.payload.value.value == 0x1235
    assert session.calls == 1


def test_print_expands_macro_and_reports_syntax_span():
    definition = MacroDefinition("N", None, (MacroToken("10"),),
        Origin(Path("config.h"), 1, "define"), MacroContext())
    context, _ = command_context(MacroCatalog((definition,)))
    assert handle_print(PrintArguments("N+1"), context).payload.value.value == 11
    failed = handle_print(PrintArguments("1+"), context)
    assert not failed.ok
    assert failed.error.code == "expression-syntax"
    assert failed.error.details["start"] == 2


def test_print_rejects_empty_and_wrong_argument_objects():
    context, _ = command_context()
    assert handle_print(PrintArguments("  "), context).error.code == "invalid-arguments"
    assert handle_print(InfoArguments("locals"), context).error.code == "invalid-arguments"


def test_info_locals_and_args_return_tables_and_reject_unknown_topic():
    context, session = command_context()
    locals_result = handle_info(InfoArguments("locals"), context)
    args_result = handle_info(InfoArguments("args"), context)
    assert locals_result.ok and locals_result.payload == ()
    assert args_result.ok and args_result.payload == ()
    assert session.calls == 2
    failed = handle_info(InfoArguments("mystery"), context)
    assert not failed.ok and failed.error.code == "invalid-arguments"
