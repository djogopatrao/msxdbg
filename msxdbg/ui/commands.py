"""Command dispatcher and handler contracts."""
from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Optional
from msxdbg.debuginfo.index import Project, VariableKind
from msxdbg.debuginfo.model import ImageId
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext
from msxdbg.debuginfo.sources import SourceRepository
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.service import EvaluationPipeline
from msxdbg.eval.tokens import ExpressionSyntaxError
from msxdbg.eval.macros import MacroExpansionError
from msxdbg.session.core import Session
from msxdbg.session.execution import ExecutionKind, ExecutionRequest
from msxdbg.session.results import ResolvedTarget, TargetQuery
from msxdbg.session.safety import DangerousAction, InteractiveEntry
from msxdbg.session.state import StepMode
from .registry import CommandArguments, CommandRegistry, CommandSpec, Completion
from .results import (BreakpointPayload, BreakpointTable, CommandError,
                      CommandResult, DisassemblyPayload, FrameTable, HelpPayload,
                      MessagePayload, PageTable, RegisterTable, SourcePayload,
                      StopPayload, SymbolPayload, UiAction)

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
    execution_timeout: Optional[float] = None
    cancellation: Optional[object] = None

@dataclass(frozen=True)
class PrintArguments:
    text: str
    type_name: Optional[str] = None

@dataclass(frozen=True)
class InfoArguments:
    topic: str
    expression: Optional[str] = None

@dataclass(frozen=True)
class FrameArguments:
    index: Optional[int] = None

@dataclass(frozen=True)
class NoArguments:
    pass

@dataclass(frozen=True)
class TargetArguments:
    target: TargetQuery

@dataclass(frozen=True)
class BreakpointNumberArguments:
    number: int

@dataclass(frozen=True)
class ListArguments:
    navigation: Optional[str] = None
    path: Optional[str] = None
    line: Optional[int] = None

@dataclass(frozen=True)
class DisassembleArguments:
    navigation: Optional[str] = None
    target: Optional[TargetQuery] = None
    count: int = 10

@dataclass(frozen=True)
class ModeArguments:
    mode: Optional[str] = None

@dataclass(frozen=True)
class ConfirmationArguments:
    confirmed: bool = False

def _completion_span(request):
    cursor = max(0, min(request.cursor, len(request.text)))
    start = request.text.rfind(" ", 0, cursor) + 1
    return start, cursor, request.text[start:cursor]

def _complete_values(request, values):
    start, end, prefix = _completion_span(request)
    return tuple(Completion(value, start, end) for value in sorted(set(values))
                 if value.startswith(prefix))

def _no_completion(request): return ()
def _target_completion(request):
    return _complete_values(request, tuple(request.catalog.symbols) +
                            tuple(path + ":" for path in request.catalog.files))
def _print_completion(request):
    return _complete_values(request, tuple(request.catalog.symbols) +
                            tuple(request.catalog.types) + ("hex", "bin"))
def _info_completion(request):
    before = request.text[:request.cursor].split()
    if len(before) <= 2:
        return _complete_values(request, ("registers", "reg", "regs", "breakpoints",
            "break", "b", "pages", "page", "slots", "segments", "symbol", "sym",
            "page3", "free", "locals", "local", "args", "arguments"))
    return _target_completion(request)
def _mode_completion(request):
    return _complete_values(request, ("c", "source", "asm", "assembly"))
def _navigation_completion(request):
    return _complete_values(request, tuple(request.catalog.symbols) +
                            tuple(path + ":" for path in request.catalog.files) +
                            ("next", "previous"))

def _parse_print(text: str) -> PrintArguments:
    text = text.strip()
    type_name = None
    primitive_types = {"bool", "char", "i8", "u8", "i16", "u16", "i32", "u32",
                       "i64", "u64", "f32", "float", "int", "unsigned", "ptr"}
    pieces = text.rsplit(None, 1)
    if len(pieces) == 2 and pieces[1] in primitive_types:
        text, type_name = pieces
    return PrintArguments(text, type_name)

def _parse_info(text: str) -> InfoArguments:
    topic, separator, remainder = text.strip().partition(" ")
    if not topic:
        raise ValueError("info requires a topic")
    if topic in ("symbol", "sym"):
        if not separator or not remainder.strip():
            raise ValueError("info symbol requires an expression")
        return InfoArguments(topic, remainder.strip())
    if separator and remainder.strip():
        raise ValueError(f"info {topic} does not accept arguments")
    return InfoArguments(topic)

def _parse_no_arguments(command: str, text: str):
    if text.strip():
        raise ValueError(f"{command} does not accept arguments")
    return NoArguments()

def _parse_frame(text: str) -> FrameArguments:
    text = text.strip()
    if not text:
        return FrameArguments()
    if not text.isdecimal():
        raise ValueError("frame requires a non-negative integer index")
    return FrameArguments(int(text))

def _parse_target_arguments(command: str, text: str) -> TargetArguments:
    if not text.strip():
        raise ValueError(f"{command} requires a target")
    return TargetArguments(parse_target(text))

def _parse_breakpoint_number(command: str, text: str) -> BreakpointNumberArguments:
    value = text.strip()
    if not value.isdecimal() or int(value) <= 0:
        raise ValueError(f"{command} requires a positive local breakpoint number")
    return BreakpointNumberArguments(int(value))

def _parse_list(text: str) -> ListArguments:
    value = text.strip()
    if not value:
        return ListArguments()
    if value in ("next", "previous"):
        return ListArguments(navigation=value)
    if value.isdecimal() and int(value) > 0:
        return ListArguments(line=int(value))
    path, separator, line = value.rpartition(":")
    if separator and path and line.isdecimal() and int(line) > 0:
        return ListArguments(path=path, line=int(line))
    raise ValueError("list expects a positive line, file:line, next, or previous")

def _parse_disassemble(text: str) -> DisassembleArguments:
    pieces = text.split()
    if not pieces:
        return DisassembleArguments()
    if pieces[0] in ("next", "previous"):
        if len(pieces) != 1:
            raise ValueError("disassemble navigation does not accept a count")
        return DisassembleArguments(navigation=pieces[0])
    if len(pieces) > 2:
        raise ValueError("disassemble expects a target and optional count")
    count = 10
    if len(pieces) == 2:
        if not pieces[1].isdecimal() or int(pieces[1]) <= 0:
            raise ValueError("disassemble count must be positive")
        count = int(pieces[1])
    return DisassembleArguments(target=parse_target(pieces[0]), count=count)

def _parse_mode(text: str) -> ModeArguments:
    value = text.strip()
    aliases = {"c": "c", "source": "c", "asm": "asm", "assembly": "asm"}
    if not value:
        return ModeArguments()
    if value not in aliases:
        raise ValueError("mode expects c, source, asm, or assembly")
    return ModeArguments(aliases[value])

def _parse_confirmation(command: str, text: str) -> ConfirmationArguments:
    value = text.strip()
    if value not in ("", "yes"):
        raise ValueError(f"{command} accepts only the literal confirmation 'yes'")
    return ConfirmationArguments(value == "yes")

def build_registry() -> CommandRegistry:
    registry = CommandRegistry()
    def add(name, aliases, help_text, syntax, repeatable, confirmation, parser, handler,
            completer=_no_completion):
        registry.register(CommandSpec(name, aliases, help_text, syntax, repeatable,
            confirmation, parser, handler, completer))
    add("break", ("b",), "Create a breakpoint", "break TARGET", True, None,
        lambda text: _parse_target_arguments("break", text), handle_break, _target_completion)
    add("delete", ("d",), "Delete a breakpoint", "delete N", True, None,
        lambda text: _parse_breakpoint_number("delete", text), handle_delete)
    add("suspend", ("disable",), "Suspend a breakpoint", "suspend N", True, None,
        lambda text: _parse_breakpoint_number("suspend", text), handle_suspend)
    add("resume", ("enable",), "Resume a breakpoint", "resume N", True, None,
        lambda text: _parse_breakpoint_number("resume", text), handle_resume)
    for name, aliases, handler in (("continue", ("c",), handle_continue),
            ("step", ("s",), handle_step), ("next", ("n",), handle_next),
            ("stepi", ("si",), handle_stepi), ("finish", (), handle_finish),
            ("where", (), handle_where)):
        add(name, aliases, f"Execute {name}", name, True, None,
            lambda text, command=name: _parse_no_arguments(command, text), handler)
    add("until", ("advance",), "Run until a target", "until TARGET", True, None,
        lambda text: _parse_target_arguments("until", text), handle_until, _target_completion)
    add("backtrace", ("bt",), "Show the call stack", "backtrace", True, None,
        lambda text: _parse_no_arguments("backtrace", text), handle_backtrace)
    add("frame", (), "Show or select a stack frame", "frame [N]", True, None,
        _parse_frame, handle_frame)
    add("list", ("l",), "List source code", "list [[FILE:]LINE|next|previous]",
        True, None, _parse_list, handle_list, _navigation_completion)
    add("disassemble", ("disas",), "Disassemble instructions",
        "disassemble [TARGET [COUNT]|next|previous]", True, None,
        _parse_disassemble, handle_disassemble, _navigation_completion)
    registry.register(CommandSpec("print", ("p", "?"), "Evaluate an expression",
        "print[/TYPE] EXPRESSION [TYPE]", True, None, _parse_print,
        handle_print, _print_completion))
    registry.register(CommandSpec("info", (), "Inspect debugger state",
        "info TOPIC [EXPRESSION]", True, None, _parse_info,
        handle_info, _info_completion))
    add("mode", (), "Show or set source mode", "mode [c|asm]", True, None,
        _parse_mode, handle_mode, _mode_completion)
    add("save", (), "Save emulator state", "save", True, None,
        lambda text: _parse_no_arguments("save", text), handle_save)
    add("reset", (), "Reset with explicit confirmation", "reset [yes]", False,
        DangerousAction.RESET, lambda text: _parse_confirmation("reset", text), handle_reset)
    add("load", (), "Load saved state with explicit confirmation", "load [yes]", False,
        DangerousAction.LOAD, lambda text: _parse_confirmation("load", text), handle_load)
    for name, aliases, handler in (("clear", (), handle_clear),
            ("help", (), handle_help), ("quit", ("q", "exit"), handle_quit)):
        add(name, aliases, name.capitalize(), name, name != "quit", None,
            lambda text, command=name: _parse_no_arguments(command, text), handler)
    return registry

def parse_target(text: str) -> TargetQuery:
    value = text.strip()
    if not value or any(character.isspace() for character in value):
        raise ValueError("target must be one non-empty token")
    image = None
    if "::" in value:
        qualifier, value = value.split("::", 1)
        if not qualifier or not value or "::" in value:
            raise ValueError("invalid image qualifier")
        image = ImageId(qualifier)
    if re.fullmatch(r"0[xX][0-9A-Fa-f]+", value):
        address = int(value, 16)
        if address > 0xFFFF:
            raise ValueError("address exceeds 16-bit CPU space")
        return TargetQuery(address=address, image=image)
    if value.isdecimal():
        address = int(value)
        if address > 0xFFFF:
            raise ValueError("address exceeds 16-bit CPU space")
        return TargetQuery(address=address, image=image)
    path, separator, line = value.rpartition(":")
    if separator:
        if not path or not line.isdecimal() or int(line) <= 0:
            raise ValueError("source target requires file:positive-line")
        return TargetQuery(path=path, line=int(line), image=image)
    if any(character in value for character in "+-*/[]()"):
        raise ValueError("target expressions are not supported")
    return TargetQuery(symbol=value, image=image)

class CommandDispatcher:
    def __init__(self, registry: Optional[CommandRegistry] = None) -> None:
        self._registry = registry or build_registry()

    def specification(self, text: str) -> Optional[CommandSpec]:
        command = text.strip().partition(" ")[0].split("/", 1)[0]
        try: return self._registry.lookup(command)
        except KeyError: return None

    def dispatch(self, text: str, context: CommandContext) -> CommandResult:
        stripped = text.strip()
        if not stripped:
            return _argument_error("", "empty command")
        command, separator, remainder = stripped.partition(" ")
        type_name = None
        if command.startswith("print/"):
            type_name = command.split("/", 1)[1]
            command = "print"
            if not type_name:
                return _argument_error("print", "print type must not be empty")
        try:
            specification = self._registry.lookup(command)
        except KeyError:
            return CommandResult(command, False,
                error=CommandError("unknown-command", f"unknown command: {command}", {}))
        try:
            arguments = specification.parser(remainder if separator else "")
            if (specification.name == "print" and isinstance(arguments, PrintArguments)
                    and arguments.type_name is None):
                pieces = arguments.text.rsplit(None, 1)
                if len(pieces) == 2 and context.project.lookup_type(pieces[1]).status == "unique":
                    arguments = PrintArguments(pieces[0], pieces[1])
            if type_name is not None:
                if not isinstance(arguments, PrintArguments):
                    raise ValueError("type suffix is valid only for print")
                if arguments.type_name is not None:
                    raise ValueError("print type was specified twice")
                arguments = PrintArguments(arguments.text, type_name)
            return specification.handler(arguments, context)
        except NotImplementedError as error:
            return CommandResult(specification.name, False, error=CommandError(
                "not-implemented", str(error), {}))
        except ValueError as error:
            return _argument_error(specification.name, str(error))

def _handler(name: str): raise NotImplementedError(f"ui.{name} is not implemented")

class _NeverCancelled:
    def is_cancelled(self) -> bool: return False

def _resolved_target(command: str, query: TargetQuery, context: CommandContext):
    resolution = context.session.resolve_target(query)
    if resolution.status != "unique":
        return None, CommandResult(command, False, error=CommandError(
            "target-" + resolution.status,
            f"target is {resolution.status}",
            {"candidate_count": len(resolution.candidates)},
        ))
    return resolution.unique_or_none(), None

def handle_break(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, TargetArguments): return _argument_error("break", "invalid target")
    try:
        target, error = _resolved_target("break", arguments.target, context)
        if error: return error
        record = context.session.add_breakpoint(target)
        return CommandResult("break", True, payload=BreakpointPayload(record, "created"))
    except Exception as error: return _session_error("break", error)

def _breakpoint_operation(command, arguments, context, operation):
    if not isinstance(arguments, BreakpointNumberArguments):
        return _argument_error(command, "invalid breakpoint number")
    try:
        payload = operation(arguments.number)
        return CommandResult(command, True, payload=BreakpointPayload(payload, command))
    except (ValueError, IndexError) as error: return _argument_error(command, str(error))
    except Exception as error: return _session_error(command, error)

def handle_delete(arguments, context):
    return _breakpoint_operation("delete", arguments, context, context.session.delete_breakpoint)
def handle_suspend(arguments, context):
    return _breakpoint_operation("suspend", arguments, context, context.session.suspend_breakpoint)
def handle_resume(arguments, context):
    return _breakpoint_operation("resume", arguments, context, context.session.resume_breakpoint)

def _execute(command, kind, arguments, context, address=None, mode=StepMode.SOURCE):
    if not isinstance(arguments, (NoArguments, TargetArguments)):
        return _argument_error(command, "invalid execution arguments")
    try:
        request = ExecutionRequest(kind, address, mode, context.execution_timeout)
        result = context.session.execute(request, context.cancellation or _NeverCancelled())
        return CommandResult(command, True, payload=StopPayload(result))
    except Exception as error: return _session_error(command, error)

def handle_continue(arguments, context): return _execute("continue", ExecutionKind.CONTINUE, arguments, context)
def handle_step(arguments, context): return _execute("step", ExecutionKind.STEP, arguments, context)
def handle_next(arguments, context): return _execute("next", ExecutionKind.NEXT, arguments, context)
def handle_stepi(arguments, context): return _execute("stepi", ExecutionKind.STEPI, arguments, context, mode=StepMode.ASSEMBLY)
def handle_finish(arguments, context): return _execute("finish", ExecutionKind.FINISH, arguments, context)
def handle_until(arguments, context):
    if not isinstance(arguments, TargetArguments): return _argument_error("until", "invalid target")
    try:
        target, error = _resolved_target("until", arguments.target, context)
        if error: return error
        return _execute("until", ExecutionKind.UNTIL, arguments, context, target.address)
    except Exception as error: return _session_error("until", error)
def handle_where(arguments, context):
    if not isinstance(arguments, NoArguments): return _argument_error("where", "invalid arguments")
    try: return CommandResult("where", True, payload=StopPayload(context.session.where()))
    except Exception as error: return _session_error("where", error)
def handle_backtrace(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, NoArguments):
        return _argument_error("backtrace", "backtrace does not accept arguments")
    try:
        trace = context.session.backtrace()
        selected = context.session.inspection().frame.index
        return CommandResult("backtrace", True,
                             payload=FrameTable(trace.frames, selected, trace.termination_reason))
    except Exception as error:
        return _session_error("backtrace", error)

def handle_frame(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, FrameArguments):
        return _argument_error("frame", "invalid frame arguments")
    try:
        frame = (context.session.inspection().frame if arguments.index is None
                 else context.session.select_frame(arguments.index))
        return CommandResult("frame", True, payload=FrameTable((frame,), frame.index))
    except (IndexError, ValueError) as error:
        return _argument_error("frame", str(error))
    except Exception as error:
        return _session_error("frame", error)
def handle_list(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, ListArguments): return _argument_error("list", "invalid arguments")
    try:
        source = None
        if arguments.navigation:
            if context.navigation.source.line is None: raise ValueError("no source navigation context")
            delta = 11 if arguments.navigation == "next" else -11
            line = max(1, context.navigation.source.line + delta)
            path = context.navigation.source.path
            match = context.project.resolve_line(path, line)
            source = match.unique_or_none().location.source if match.status == "unique" else None
        elif arguments.line is not None:
            path = arguments.path or context.navigation.source.path
            if path is None: raise ValueError("a source file is required")
            match = context.project.resolve_line(path, arguments.line)
            source = match.unique_or_none().location.source if match.status == "unique" else None
        else:
            location = context.session.where().snapshot.pc_resolution.unique_or_none()
            source = location.source if location is not None else None
        if source is None: raise ValueError("source location is unavailable or ambiguous")
        window = context.sources.read_window(source, 5, 5)
        context.navigation.source.path = source.path
        context.navigation.source.line = source.line
        return CommandResult("list", True, payload=SourcePayload(window), warnings=window.diagnostics)
    except ValueError as error: return _argument_error("list", str(error))
    except Exception as error: return _session_error("list", error)

def handle_disassemble(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, DisassembleArguments):
        return _argument_error("disassemble", "invalid arguments")
    try:
        if arguments.navigation:
            if context.navigation.disassembly.address is None:
                raise ValueError("no disassembly navigation context")
            address = context.navigation.disassembly.address
            if arguments.navigation == "previous": address = max(0, address - 20)
        elif arguments.target is not None:
            target, error = _resolved_target("disassemble", arguments.target, context)
            if error: return error
            address = target.address
        else:
            address = context.session.inspection().registers.get("PC")
        result = context.session.disassemble(address, arguments.count)
        context.navigation.disassembly.address = result.next_cursor
        return CommandResult("disassemble", True, payload=DisassemblyPayload(result))
    except ValueError as error: return _argument_error("disassemble", str(error))
    except Exception as error: return _session_error("disassemble", error)
def handle_print(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, PrintArguments):
        return _argument_error("print", "invalid print arguments")
    if not arguments.text.strip():
        return _argument_error("print", "print requires an expression")
    try:
        payload = EvaluationPipeline(context.project, context.evaluator).evaluate_print(
            arguments.text, context.macros, context.macro_context,
            context.session.inspection, arguments.type_name,
        )
        return CommandResult("print", True, payload=payload)
    except Exception as error:
        return _evaluation_error("print", error)

def handle_info(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, InfoArguments):
        return _argument_error("info", "invalid info arguments")
    aliases = {"locals": VariableKind.LOCALS, "local": VariableKind.LOCALS,
               "args": VariableKind.PARAMETERS, "arguments": VariableKind.PARAMETERS}
    kind = aliases.get(arguments.topic)
    try:
        if kind is not None:
            payload = EvaluationPipeline(context.project, context.evaluator).evaluate_variables(
                kind, context.session.inspection)
        elif arguments.topic in ("registers", "reg", "regs"):
            payload = RegisterTable(context.session.inspection().registers)
        elif arguments.topic in ("breakpoints", "break", "b"):
            payload = BreakpointTable(context.session.breakpoints())
        elif arguments.topic in ("pages", "page", "slots", "segments"):
            payload = PageTable(context.session.pages())
        elif arguments.topic in ("symbol", "sym"):
            address = EvaluationPipeline(context.project, context.evaluator).evaluate_address(
                arguments.expression, context.macros, context.macro_context,
                context.session.inspection)
            payload = SymbolPayload(context.project.nearest_symbol(address))
        elif arguments.topic in ("page3", "free"):
            payload = context.session.page3(None)
        else:
            return _argument_error("info", f"unsupported info topic: {arguments.topic}")
        return CommandResult("info", True, payload=payload)
    except Exception as error:
        return _evaluation_error("info", error)
def handle_mode(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, ModeArguments): return _argument_error("mode", "invalid arguments")
    try:
        if arguments.mode is not None:
            context.session.set_mode(StepMode.SOURCE if arguments.mode == "c" else StepMode.ASSEMBLY)
        mode = arguments.mode or context.session.mode.value
        return CommandResult("mode", True, payload=MessagePayload(mode))
    except Exception as error: return _session_error("mode", error)

def handle_save(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, NoArguments): return _argument_error("save", "invalid arguments")
    try:
        context.session.save(); return CommandResult("save", True, payload=MessagePayload("saved"))
    except Exception as error: return _session_error("save", error)

def _dangerous(command, action, arguments, context, operation):
    if not isinstance(arguments, ConfirmationArguments):
        return _argument_error(command, "invalid confirmation")
    if not arguments.confirmed:
        return CommandResult(command, True, payload=MessagePayload(
            f"type '{command} yes' as fresh interactive input to confirm"))
    if context.input_origin != "interactive":
        return CommandResult(command, False, error=CommandError(
            "unsafe-input-origin", f"{command} is interactive-only", {}))
    try:
        permit = context.session.authorize(action, InteractiveEntry(f"{command} yes", True))
        operation(permit)
        return CommandResult(command, True, payload=MessagePayload(command + " complete"))
    except Exception as error: return _session_error(command, error)

def handle_reset(arguments, context):
    return _dangerous("reset", DangerousAction.RESET, arguments, context,
                      lambda permit: context.session.reset(permit))
def handle_load(arguments, context):
    return _dangerous("load", DangerousAction.LOAD, arguments, context,
                      lambda permit: context.session.load(permit))
def handle_clear(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, NoArguments): return _argument_error("clear", "invalid arguments")
    return CommandResult("clear", True, payload=UiAction(UiAction.CLEAR))
def handle_help(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, NoArguments): return _argument_error("help", "invalid arguments")
    entries = tuple((spec.name, spec.syntax, spec.help_text)
                    for spec in build_registry().specifications())
    return CommandResult("help", True, payload=HelpPayload(entries))
def handle_quit(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, NoArguments): return _argument_error("quit", "invalid arguments")
    return CommandResult("quit", True, payload=UiAction(UiAction.QUIT))

def _argument_error(command: str, message: str) -> CommandResult:
    return CommandResult(command, False, error=CommandError("invalid-arguments", message, {}))

def _evaluation_error(command: str, error: Exception) -> CommandResult:
    if isinstance(error, ExpressionSyntaxError):
        details = {"start": error.start, "end": error.end}
        code = "expression-syntax"
    elif isinstance(error, MacroExpansionError):
        details = {}; code = "macro-expansion"
    else:
        details = {"error_type": type(error).__name__}; code = "evaluation"
    return CommandResult(command, False,
                         error=CommandError(code, str(error), details))

def _session_error(command: str, error: Exception) -> CommandResult:
    return CommandResult(command, False, error=CommandError(
        "session", str(error), {"error_type": type(error).__name__}
    ))

__all__ = ["BreakpointNumberArguments", "CommandContext", "CommandDispatcher",
           "ConfirmationArguments", "DisassembleArguments", "DisassemblyCursor",
           "FrameArguments", "InfoArguments", "ListArguments", "ModeArguments",
           "NavigationState", "NoArguments", "PrintArguments", "SourceCursor",
           "TargetArguments", "build_registry", "handle_backtrace", "handle_frame",
           "handle_info", "handle_print", "parse_target"]
