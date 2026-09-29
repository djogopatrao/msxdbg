"""Text dispatch for Phase 3 commands."""

from msxdbg.debuginfo.index import CompletionCatalog
from msxdbg.debuginfo.model import Image, ImageId, TypeDef, TypeId
from msxdbg.debuginfo.index import Project
from msxdbg.eval.evaluator import Evaluator
from msxdbg.eval.values import ValueDecoder, ValueLimits
from msxdbg.ui.commands import CommandDispatcher, build_registry
from msxdbg.ui.registry import CompletionRequest
from test_phase3_handlers import command_context


def test_dispatch_print_alias_and_type_suffix():
    context, session = command_context()
    dispatcher = CommandDispatcher()
    assert dispatcher.dispatch("print 2 + 3", context).payload.value.value == 5
    assert dispatcher.dispatch("p 4*5", context).payload.value.value == 20
    typed = dispatcher.dispatch("print/u16 0x100", context)
    assert not typed.ok  # this context intentionally has no memory reader
    assert session.calls == 1


def test_dispatch_info_and_structured_errors():
    context, _ = command_context()
    dispatcher = CommandDispatcher()
    assert dispatcher.dispatch("info locals", context).ok
    assert dispatcher.dispatch("info", context).error.code == "invalid-arguments"
    assert dispatcher.dispatch("unknown thing", context).error.code == "unknown-command"
    assert dispatcher.dispatch("   ", context).error.code == "invalid-arguments"


def test_registry_rejects_duplicates_without_partial_registration():
    registry = build_registry()
    original = registry.specifications()
    try:
        registry.register(original[0])
    except ValueError:
        pass
    else:
        raise AssertionError("duplicate registration succeeded")
    assert registry.specifications() == original


def test_registry_completion_uses_commands_then_offline_catalog():
    registry = build_registry()
    commands = registry.complete(CompletionRequest("pr", 2, CompletionCatalog()))
    assert [item.value for item in commands] == ["print"]
    catalog = CompletionCatalog(symbols=("player", "points"), types=("Player",))
    values = registry.complete(CompletionRequest("print po", 8, catalog))
    assert [item.value for item in values] == ["points"]


def test_dispatch_recognizes_loaded_struct_type_at_end_of_print():
    context, _ = command_context()
    struct = TypeDef(TypeId("Player"), "Player", "struct", 1)
    context.project = Project((Image(ImageId("app"), types=(struct,)),))
    context.evaluator = Evaluator(context.project, ValueDecoder(), ValueLimits())
    result = CommandDispatcher().dispatch("print 0x100 Player", context)
    assert not result.ok
    assert result.error.code == "evaluation"  # parsed as typed memory; fake context has no reader


def test_complete_registry_metadata_and_handler_failures_are_structured():
    registry = build_registry()
    assert len(registry.specifications()) == 24
    assert registry.lookup("b") is registry.lookup("break")
    assert registry.lookup("disable") is registry.lookup("suspend")
    assert registry.lookup("disas") is registry.lookup("disassemble")
    assert registry.lookup("?") is registry.lookup("print")
    assert registry.lookup("reset").confirmation.value == "reset"
    assert registry.lookup("load").confirmation.value == "load"
    context, _ = command_context()
    result = CommandDispatcher(registry).dispatch("break main", context)
    assert not result.ok and result.command == "break"
    assert result.error.code == "session"


def test_command_specific_completion():
    registry = build_registry()
    catalog = CompletionCatalog(symbols=("player",), types=("Player",),
                                files=("src/main.c",))
    assert [item.value for item in registry.complete(
        CompletionRequest("info re", 7, catalog))] == ["reg", "registers", "regs"]
    assert [item.value for item in registry.complete(
        CompletionRequest("mode a", 6, catalog))] == ["asm", "assembly"]
    assert [item.value for item in registry.complete(
        CompletionRequest("break src", 9, catalog))] == ["src/main.c:"]
    values = [item.value for item in registry.complete(
        CompletionRequest("print P", 7, catalog))]
    assert values == ["Player"]
