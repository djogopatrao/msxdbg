"""Contextual macro lookup and bounded token expansion."""
from pathlib import Path
import pytest
from msxdbg.debuginfo.diagnostics import Origin
from msxdbg.debuginfo.macros import (MacroCatalog, MacroContext, MacroDefinition,
    MacroToken, parse_macro_definitions)
from msxdbg.debuginfo.model import ImageId, ResolutionStatus
from msxdbg.eval.macros import ExpansionLimits, MacroExpander, MacroExpansionError
from msxdbg.eval.parser import ExpressionParser
from msxdbg.eval.tokens import tokenize

origin = Origin(Path("config.h"), 4, "define")
context = MacroContext(ImageId("app"), "main.c")

def macro(name, replacement, parameters=None, at=context):
    return MacroDefinition(name, parameters, tuple(MacroToken(item) for item in replacement), origin, at)
def expand(text, *definitions, limits=ExpansionLimits()):
    return MacroExpander().expand(tokenize(text), MacroCatalog(definitions), context, limits)
def lexemes(expanded): return [token.lexeme for token in expanded.tokens]

def test_catalog_prefers_specific_context_and_reports_ambiguity():
    global_ = macro("N", ("1",), at=MacroContext()); local = macro("N", ("2",))
    catalog = MacroCatalog((global_, local))
    assert catalog.lookup("N", context).candidates == (local,)
    assert catalog.names(context) == ("N",)
    conflict = MacroCatalog((local, macro("N", ("3",))))
    assert conflict.lookup("N", context).status == ResolutionStatus.AMBIGUOUS
    assert conflict.names(context) == ()

def test_object_macros_chain_with_textual_precedence():
    result = expand("M*3", macro("M", ("1", "+", "2")))
    assert lexemes(result) == ["1", "+", "2", "*", "3"]
    expression = ExpressionParser().parse_expression("".join(lexemes(result)))
    assert expression.left.value == 1

def test_function_macro_substitutes_repeated_and_nested_arguments():
    add = macro("ADD", ("(", "a", ")", "+", "(", "b", ")"), ("a", "b"))
    twice = macro("TWICE", ("ADD", "(", "x", ",", "x", ")"), ("x",))
    result = expand("TWICE(1+2)", add, twice)
    assert lexemes(result).count("1") == 2
    assert lexemes(result).count("2") == 2

def test_zero_argument_macro_and_nested_comma_parsing():
    zero = macro("ZERO", ("0",), ()); first = macro("FIRST", ("a",), ("a", "b"))
    assert lexemes(expand("ZERO()", zero)) == ["0"]
    assert lexemes(expand("FIRST((1+2),3)", first)) == ["(", "1", "+", "2", ")"]

def test_missing_macro_is_left_for_name_resolution():
    assert lexemes(expand("UNKNOWN+1")) == ["UNKNOWN", "+", "1"]

def test_ambiguous_arity_cycle_and_limits_are_explicit():
    with pytest.raises(MacroExpansionError, match="ambiguous"):
        expand("N", macro("N", ("1",)), macro("N", ("2",)))
    with pytest.raises(MacroExpansionError, match="expects 2"):
        expand("F(1)", macro("F", ("a",), ("a", "b")))
    with pytest.raises(MacroExpansionError, match="cycle"):
        expand("A", macro("A", ("B",)), macro("B", ("A",)))
    with pytest.raises(MacroExpansionError, match="token limit"):
        expand("LOTS", macro("LOTS", ("1", "+", "2")), limits=ExpansionLimits(max_tokens=2))

def test_builtins_are_reserved_from_macro_expansion():
    assert lexemes(expand("hex(10)", macro("hex", ("99",)))) == ["hex", "(", "10", ")"]

def test_parse_definitions_handles_objects_functions_continuations_and_undef():
    parsed = parse_macro_definitions("""\
#define LIMIT 0x20
#define ADD(a,b) ((a) + \\
                  (b))
#define OLD 1
#undef OLD
""", Path("config.h"), context)
    assert [item.name for item in parsed.value] == ["LIMIT", "ADD"]
    assert parsed.value[0].parameters is None
    assert parsed.value[1].parameters == ("a", "b")
    assert not parsed.diagnostics

def test_parse_definitions_skips_indeterminate_and_unsupported_macros():
    parsed = parse_macro_definitions("""\
#ifdef FEATURE
#define CONDITIONAL 1
#endif
#define STRINGIFY(x) #x
#define HEX #ABCD
""", Path("config.h"), context)
    assert [item.name for item in parsed.value] == ["HEX"]
    assert {item.code for item in parsed.diagnostics} == {
        "macro.conditional-unsupported", "macro.operator-unsupported"
    }
