"""Command dispatcher and handler contracts."""
from __future__ import annotations
from dataclasses import dataclass, replace
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
from msxdbg.session.conditions import ConditionCompiler, compile_mapping_qualifier
from msxdbg.session.breakpoints import MappingQualifier
from msxdbg.session.results import ResolvedTarget, TargetQuery
from msxdbg.session.safety import DangerousAction, InteractiveEntry
from msxdbg.session.state import StepMode
from .registry import (CommandArguments, CommandRegistry, CommandSpec, Completion,
                       CompletionRequest)
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
class ContinueArguments:
    until_signature: bool = False

@dataclass(frozen=True)
class TargetArguments:
    target: TargetQuery

@dataclass(frozen=True)
class BreakArguments:
    target: TargetQuery
    condition: Optional[str] = None
    qualifier: Optional[MappingQualifier] = None

@dataclass(frozen=True)
class WatchArguments:
    access: str
    target: TargetQuery
    size: int

@dataclass(frozen=True)
class WriteMemoryArguments:
    target: TargetQuery
    data: bytes

@dataclass(frozen=True)
class WriteRegisterArguments:
    name: str
    value: int

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

def _parse_continue(text: str) -> ContinueArguments:
    value = text.strip()
    if value not in ("", "--until-signature"):
        raise ValueError("continue accepts only --until-signature")
    return ContinueArguments(value == "--until-signature")

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

def _parse_break(text: str) -> BreakArguments:
    pieces=text.split()
    if not pieces: raise ValueError("break requires a target")
    target=parse_target(pieces[0]); condition_tokens=[]
    page=primary=secondary=segment=None; index=1; in_condition=False
    while index < len(pieces):
        token=pieces[index]
        if token == "if":
            if in_condition: raise ValueError("break accepts only one condition")
            in_condition=True; index+=1; continue
        if token in ("page","slot","segment"):
            if index+1 >= len(pieces): raise ValueError(f"{token} requires a value")
            value=pieces[index+1]
            if token == "page":
                if page is not None or not value.isdecimal(): raise ValueError("invalid page qualifier")
                page=int(value)
            elif token == "segment":
                if segment is not None:
                    raise ValueError("duplicate segment qualifier")
                try: segment=int(value,0)
                except ValueError: raise ValueError("invalid segment qualifier") from None
            else:
                if primary is not None: raise ValueError("duplicate slot qualifier")
                fields=value.split(".")
                if len(fields) not in (1,2) or any(not item.isdecimal() for item in fields):
                    raise ValueError("slot expects P or P.S")
                primary=int(fields[0]); secondary=int(fields[1]) if len(fields)==2 else None
            index+=2; continue
        if not in_condition:
            raise ValueError(f"unexpected break option: {token}")
        condition_tokens.append(token); index+=1
    if in_condition and not condition_tokens: raise ValueError("break condition must not be empty")
    qualifier=(MappingQualifier(page,primary,secondary,segment)
               if any(item is not None for item in (page,primary,secondary,segment)) else None)
    return BreakArguments(target," ".join(condition_tokens) if in_condition else None,qualifier)

def _parse_watch(text: str) -> WatchArguments:
    pieces=text.split()
    if len(pieces) != 3 or pieces[0] not in ("read","write","access"):
        raise ValueError("watch expects read|write|access ADDRESS SIZE")
    try: size=int(pieces[2],0)
    except ValueError: raise ValueError("watch size must be a positive integer") from None
    if size < 1: raise ValueError("watch size must be a positive integer")
    return WatchArguments(pieces[0],parse_target(pieces[1]),size)

def _parse_write(text: str):
    pieces = text.split()
    if not pieces:
        raise ValueError("write expects memory or register")
    if pieces[0] == "register":
        if len(pieces) != 3:
            raise ValueError("write register expects NAME VALUE")
        try: value = int(pieces[2], 0)
        except ValueError: raise ValueError("register value must be an integer") from None
        return WriteRegisterArguments(pieces[1], value)
    if pieces[0] != "memory" or len(pieces) not in (3, 4, 5):
        raise ValueError("write memory expects TARGET HEXBYTES or TARGET VALUE u8|u16|u32 [little|big]")
    target = parse_target(pieces[1])
    if len(pieces) == 3:
        encoded = pieces[2].removeprefix("0x").removeprefix("0X")
        if not encoded or len(encoded) % 2 or re.fullmatch(r"[0-9A-Fa-f]+", encoded) is None:
            raise ValueError("memory bytes must contain complete hexadecimal byte pairs")
        return WriteMemoryArguments(target, bytes.fromhex(encoded))
    types = {"u8": 1, "u16": 2, "u32": 4}
    if pieces[3] not in types:
        raise ValueError("memory scalar type must be u8, u16, or u32")
    endian = pieces[4] if len(pieces) == 5 else "little"
    if endian not in ("little", "big"):
        raise ValueError("endianness must be little or big")
    try: value = int(pieces[2], 0)
    except ValueError: raise ValueError("memory value must be an integer") from None
    width = types[pieces[3]]
    if not 0 <= value < (1 << (width * 8)):
        raise ValueError("memory value is outside its declared width")
    return WriteMemoryArguments(target, value.to_bytes(width, endian))

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
        _parse_break, handle_break, _target_completion)
    add("watch", (), "Create a memory watchpoint",
        "watch read|write|access ADDRESS SIZE", True, None,
        _parse_watch, handle_watch, _target_completion)
    add("write", (), "Write memory or a CPU register",
        "write memory TARGET HEXBYTES|VALUE TYPE [ENDIAN] | write register NAME VALUE",
        True, None, _parse_write, handle_write, _target_completion)
    add("delete", ("d",), "Delete a breakpoint", "delete N", True, None,
        lambda text: _parse_breakpoint_number("delete", text), handle_delete)
    add("suspend", ("disable",), "Suspend a breakpoint", "suspend N", True, None,
        lambda text: _parse_breakpoint_number("suspend", text), handle_suspend)
    add("resume", ("enable",), "Resume a breakpoint", "resume N", True, None,
        lambda text: _parse_breakpoint_number("resume", text), handle_resume)
    add("continue", ("c",), "Continue execution", "continue [--until-signature]",
        True, None, _parse_continue, handle_continue)
    for name, aliases, handler in (("step", ("s",), handle_step), ("next", ("n",), handle_next),
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

    def complete(self, text: str, cursor: int, context: CommandContext):
        """Return deterministic, read-only completions for the current project."""
        return self._registry.complete(CompletionRequest(
            text, cursor, context.project.completion_catalog()))

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
    if isinstance(arguments, TargetArguments):
        arguments = BreakArguments(arguments.target)
    if not isinstance(arguments, BreakArguments): return _argument_error("break", "invalid target")
    try:
        target, error = _resolved_target("break", arguments.target, context)
        if error: return error
        qualifier=arguments.qualifier
        if qualifier is not None and qualifier.page is None:
            qualifier=MappingQualifier(target.address // 0x4000,
                qualifier.primary_slot,qualifier.secondary_slot,qualifier.segment)
        compiled = (ConditionCompiler(context.project).compile(arguments.condition)
                    if arguments.condition is not None else None)
        predicates=[]
        if compiled is not None: predicates.append(f"({compiled.tcl_expression})")
        if qualifier is not None: predicates.append(compile_mapping_qualifier(qualifier))
        remote_condition=" && ".join(item for item in predicates if item)
        record = context.session.add_breakpoint(target, arguments.condition,
            remote_condition or None,qualifier)
        return CommandResult("break", True, payload=BreakpointPayload(record, "created"))
    except Exception as error: return _session_error("break", error)

def handle_watch(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    if not isinstance(arguments, WatchArguments):
        return _argument_error("watch", "invalid watchpoint")
    try:
        target,error=_resolved_target("watch",arguments.target,context)
        if error: return error
        if target.address + arguments.size > 0x10000:
            return _argument_error("watch", "watchpoint range is outside CPU memory")
        record=context.session.add_watchpoint(arguments.access,target.address,arguments.size)
        return CommandResult("watch",True,payload=BreakpointPayload(record,"created"))
    except Exception as error: return _session_error("watch",error)

def handle_write(arguments: CommandArguments, context: CommandContext) -> CommandResult:
    try:
        if isinstance(arguments, WriteMemoryArguments):
            target,error=_resolved_target("write",arguments.target,context)
            if error: return error
            result=context.session.write_memory(target.address,arguments.data)
            if not result.verified:
                return CommandResult("write",False,error=CommandError(
                    "write-verification-failed", "memory differs after write",
                    {"address": result.address, "requested": result.requested.hex(),
                     "observed": result.observed.hex()}))
            return CommandResult("write",True,payload=MessagePayload(
                f"wrote {len(result.requested)} byte(s) at {result.address:#06x}; verified"))
        if isinstance(arguments, WriteRegisterArguments):
            result=context.session.write_register(arguments.name,arguments.value)
            if result.requested != result.observed:
                return CommandResult("write",False,error=CommandError(
                    "write-verification-failed", "register differs after write",
                    {"register": result.name, "requested": result.requested,
                     "observed": result.observed}))
            return CommandResult("write",True,payload=MessagePayload(
                f"{result.name} = {result.observed:#x}; verified"))
        return _argument_error("write", "invalid write arguments")
    except Exception as error:
        return _session_error("write",error)

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

def handle_continue(arguments, context):
    if not isinstance(arguments, ContinueArguments):
        return _argument_error("continue", "invalid continue arguments")
    if not arguments.until_signature:
        return _execute("continue", ExecutionKind.CONTINUE, NoArguments(), context)
    try:
        result = context.session.continue_until_signature(
            context.execution_timeout, context.cancellation or _NeverCancelled())
        return CommandResult("continue", True, payload=StopPayload(result))
    except Exception as error:
        return _session_error("continue", error)
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
            # Listing is a source-navigation operation.  The executable line is
            # useful for breakpoints, but must not silently move the requested
            # source window to that later line.
            if source is not None:
                source = replace(source, line=arguments.line,
                                 text=(source.text if source.line == arguments.line else None))
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
    details = {"error_type": type(error).__name__}
    if hasattr(error, "outcome_unknown"):
        details["outcome_unknown"] = bool(error.outcome_unknown)
    if hasattr(error, "operation"):
        details["operation"] = error.operation
    return CommandResult(command, False, error=CommandError(
        "session", str(error), details
    ))

__all__ = ["BreakpointNumberArguments", "CommandContext", "CommandDispatcher",
           "ConfirmationArguments", "DisassembleArguments", "DisassemblyCursor",
           "FrameArguments", "InfoArguments", "ListArguments", "ModeArguments",
           "NavigationState", "NoArguments", "PrintArguments", "SourceCursor",
           "TargetArguments", "WriteMemoryArguments", "WriteRegisterArguments",
           "build_registry", "handle_backtrace", "handle_frame",
           "handle_info", "handle_print", "parse_target"]
