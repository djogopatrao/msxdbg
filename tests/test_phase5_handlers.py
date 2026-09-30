"""Phase 5 handlers delegate to session use cases without transport knowledge."""

from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext
from msxdbg.debuginfo.model import Resolution, ResolutionStatus
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.values import ValueDecoder, ValueLimits
from msxdbg.session.results import ResolvedTarget
from msxdbg.session.state import StepMode
from msxdbg.ui.commands import (
    BreakpointNumberArguments, CommandContext, ConfirmationArguments, ContinueArguments,
    DisassemblyCursor, ModeArguments, NavigationState, NoArguments,
    SourceCursor, TargetArguments, handle_break, handle_clear, handle_continue,
    handle_delete, handle_help, handle_load, handle_mode, handle_quit,
    handle_reset, handle_resume, handle_save, handle_suspend, handle_until,
    handle_where, parse_target,
)
from msxdbg.ui.results import UiAction


class Session:
    def __init__(self):
        self.calls = []
        self.mode = StepMode.SOURCE

    def resolve_target(self, query):
        self.calls.append(("resolve", query))
        target = ResolvedTarget(0x1234, Resolution(ResolutionStatus.MISSING), "main")
        return Resolution(ResolutionStatus.UNIQUE, (target,))

    def add_breakpoint(self, target, condition=None, remote_condition=None, qualifier=None):
        self.calls.append(("add", target, condition, remote_condition, qualifier)); return "breakpoint"
    def delete_breakpoint(self, number): self.calls.append(("delete", number))
    def suspend_breakpoint(self, number): self.calls.append(("suspend", number)); return "suspended"
    def resume_breakpoint(self, number): self.calls.append(("resume", number)); return "resumed"
    def execute(self, request, cancel): self.calls.append(("execute", request)); return "stopped"
    def continue_until_signature(self, timeout, cancel):
        self.calls.append(("until-signature", timeout)); return "signature-stopped"
    def where(self): self.calls.append(("where",)); return "where"
    def set_mode(self, mode): self.calls.append(("mode", mode)); self.mode = mode
    def save(self): self.calls.append(("save",))
    def authorize(self, action, entry): self.calls.append(("authorize", action, entry)); return "permit"
    def reset(self, permit): self.calls.append(("reset", permit))
    def load(self, permit): self.calls.append(("load", permit))


def context(origin="interactive"):
    project = Project(())
    return CommandContext(Session(), project, object(), MacroCatalog(), MacroContext(),
        Evaluator(project, ValueDecoder(), ValueLimits()),
        NavigationState(SourceCursor(), DisassemblyCursor()), origin)


def test_breakpoint_and_execution_handlers_delegate_typed_requests():
    ctx = context(); target = TargetArguments(parse_target("main"))
    assert handle_break(target, ctx).payload.record == "breakpoint"
    assert handle_delete(BreakpointNumberArguments(2), ctx).ok
    assert handle_suspend(BreakpointNumberArguments(2), ctx).payload.record == "suspended"
    assert handle_resume(BreakpointNumberArguments(2), ctx).payload.record == "resumed"
    assert handle_continue(ContinueArguments(), ctx).payload.result == "stopped"
    assert handle_continue(ContinueArguments(True), ctx).payload.result == "signature-stopped"
    assert handle_until(target, ctx).payload.result == "stopped"
    assert handle_where(NoArguments(), ctx).payload.result == "where"
    execute_requests = [call[1] for call in ctx.session.calls if call[0] == "execute"]
    assert execute_requests[0].kind.value == "continue"
    assert execute_requests[1].kind.value == "until"
    assert execute_requests[1].address == 0x1234


def test_mode_save_actions_and_help_are_concrete_results():
    ctx = context()
    assert handle_mode(ModeArguments("asm"), ctx).payload.message == "asm"
    assert ctx.session.mode == StepMode.ASSEMBLY
    assert handle_save(NoArguments(), ctx).ok
    assert handle_clear(NoArguments(), ctx).payload == UiAction(UiAction.CLEAR)
    assert handle_quit(NoArguments(), ctx).payload == UiAction(UiAction.QUIT)
    help_result = handle_help(NoArguments(), ctx)
    assert help_result.ok and len(help_result.payload.entries) == 26


def test_dangerous_handlers_require_fresh_interactive_confirmation():
    ctx = context()
    explanation = handle_reset(ConfirmationArguments(False), ctx)
    assert explanation.ok and not ctx.session.calls
    assert handle_reset(ConfirmationArguments(True), ctx).ok
    assert handle_load(ConfirmationArguments(True), ctx).ok
    assert [call[0] for call in ctx.session.calls] == [
        "authorize", "reset", "authorize", "load"]

    batch = context("batch")
    refused = handle_reset(ConfirmationArguments(True), batch)
    assert not refused.ok and refused.error.code == "unsafe-input-origin"
    assert batch.session.calls == []


def test_missing_and_ambiguous_targets_do_not_mutate_breakpoints():
    ctx = context()
    candidate = ResolvedTarget(0x1234, Resolution(ResolutionStatus.MISSING), "main")
    ctx.session.resolve_target = lambda query: Resolution(
        ResolutionStatus.AMBIGUOUS, (candidate, candidate))
    result = handle_break(TargetArguments(parse_target("main")), ctx)
    assert not result.ok and result.error.code == "target-ambiguous"
    assert not any(call[0] == "add" for call in ctx.session.calls)
