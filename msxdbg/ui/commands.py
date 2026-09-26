"""Command dispatcher and handler contracts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext
from msxdbg.debuginfo.sources import SourceRepository
from msxdbg.eval.evaluator import Evaluator
from msxdbg.session.core import Session
from msxdbg.session.results import TargetQuery
from .registry import CommandArguments, CommandRegistry
from .results import CommandResult

@dataclass
class SourceCursor: path: Optional[str] = None; line: Optional[int] = None
@dataclass
class DisassemblyCursor: address: Optional[int] = None
@dataclass
class NavigationState:
    source: SourceCursor
    disassembly: DisassemblyCursor
@dataclass
class CommandContext:
    session: Session
    project: Project
    sources: SourceRepository
    macros: MacroCatalog
    macro_context: MacroContext
    evaluator: Evaluator
    navigation: NavigationState
    input_origin: str

def build_registry() -> CommandRegistry: raise NotImplementedError("ui.build_registry is not implemented")
def parse_target(text: str) -> TargetQuery: raise NotImplementedError("ui.parse_target is not implemented")

class CommandDispatcher:
    def dispatch(self, text: str, context: CommandContext) -> CommandResult:
        raise NotImplementedError("CommandDispatcher.dispatch is not implemented")

def _handler(name: str): raise NotImplementedError(f"ui.{name} is not implemented")
def handle_break(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_break")
def handle_delete(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_delete")
def handle_suspend(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_suspend")
def handle_resume(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_resume")
def handle_continue(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_continue")
def handle_step(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_step")
def handle_next(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_next")
def handle_stepi(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_stepi")
def handle_finish(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_finish")
def handle_until(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_until")
def handle_where(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_where")
def handle_backtrace(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_backtrace")
def handle_frame(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_frame")
def handle_list(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_list")
def handle_disassemble(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_disassemble")
def handle_print(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_print")
def handle_info(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_info")
def handle_mode(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_mode")
def handle_save(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_save")
def handle_reset(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_reset")
def handle_load(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_load")
def handle_clear(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_clear")
def handle_help(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_help")
def handle_quit(arguments: CommandArguments, context: CommandContext) -> CommandResult: return _handler("handle_quit")

__all__ = ["CommandContext", "CommandDispatcher", "DisassemblyCursor", "NavigationState", "SourceCursor", "build_registry", "parse_target"]
