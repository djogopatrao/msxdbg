"""Contracts for the restricted C-header type parser."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
import operator
import re
from typing import Dict, Sequence, TYPE_CHECKING, Tuple

from .diagnostics import Diagnostic, Origin, ParseResult
from .model import Field, TypeDef, TypeId
from .macros import MacroContext, parse_macro_definitions
from ._types import PRIMITIVES, TYPE_ALIASES

if TYPE_CHECKING:
    from .macros import MacroDefinition


@dataclass(frozen=True)
class HeaderInput:
    """Explicit header content and its physical path."""

    path: Path
    text: str


@dataclass(frozen=True)
class HeaderTypes:
    """Types and macro definitions accepted from the restricted grammar."""

    types: Tuple[TypeDef, ...] = ()
    macros: Tuple["MacroDefinition", ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "types", tuple(self.types))
        object.__setattr__(self, "macros", tuple(self.macros))


def parse_headers(inputs: Sequence[HeaderInput]) -> ParseResult[HeaderTypes]:
    """Parse explicitly supplied headers without importing the evaluator."""

    diagnostics = []
    macros = []
    declarations = {}
    origins = {}
    for item in inputs:
        macro_result = parse_macro_definitions(item.text, item.path, MacroContext())
        macros.extend(macro_result.value)
        diagnostics.extend(macro_result.diagnostics)
        text = re.sub(r"/\*.*?\*/", " ", item.text, flags=re.S)
        text = re.sub(r"//[^\n]*", " ", text)
        # Conditional regions are intentionally ignored rather than guessed.
        text = re.sub(r"^\s*#\s*(?:if|ifdef|ifndef)\b.*?^\s*#\s*endif\b.*?$",
                      " ", text, flags=re.M | re.S)
        pattern = re.compile(
            r"(?:typedef\s+)?struct(?:\s+([A-Za-z_]\w*))?\s*\{(.*?)\}\s*([A-Za-z_]\w*)?\s*;",
            re.S,
        )
        for match in pattern.finditer(text):
            tag, body, alias = match.groups()
            name = alias or tag
            line = text[:match.start()].count("\n") + 1
            if not name:
                diagnostics.append(Diagnostic("header.anonymous-struct", "warning",
                    "anonymous struct without typedef name is unsupported",
                    (Origin(item.path, line, "struct"),)))
                continue
            if name in declarations:
                diagnostics.append(Diagnostic("header.duplicate-type", "warning",
                    f"duplicate header type {name}",
                    (origins[name], Origin(item.path, line, "struct"))))
                declarations[name] = None
                continue
            declarations[name] = body
            origins[name] = Origin(item.path, line, "struct")

    primitive = {item.name: item for item in PRIMITIVES}
    object_macros = {item.name: "".join(token.lexeme for token in item.replacement)
                     for item in macros if item.parameters is None}

    binary_ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                  ast.FloorDiv: operator.floordiv, ast.Div: operator.floordiv,
                  ast.Mod: operator.mod, ast.LShift: operator.lshift,
                  ast.RShift: operator.rshift, ast.BitAnd: operator.and_,
                  ast.BitOr: operator.or_, ast.BitXor: operator.xor}
    unary_ops = {ast.UAdd: operator.pos, ast.USub: operator.neg,
                 ast.Invert: operator.invert}
    def constant(text, stack=()):
        def visit(node):
            if isinstance(node, ast.Expression): return visit(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, int): return node.value
            if isinstance(node, ast.Name):
                if node.id in stack or node.id not in object_macros:
                    raise ValueError(f"unknown or recursive array bound {node.id}")
                return constant(object_macros[node.id], stack + (node.id,))
            if isinstance(node, ast.BinOp) and type(node.op) in binary_ops:
                right = visit(node.right)
                if right == 0 and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
                    raise ValueError("division by zero in array bound")
                return binary_ops[type(node.op)](visit(node.left), right)
            if isinstance(node, ast.UnaryOp) and type(node.op) in unary_ops:
                return unary_ops[type(node.op)](visit(node.operand))
            raise ValueError("unsupported array-bound expression")
        value = visit(ast.parse(text, mode="eval"))
        if not isinstance(value, int) or value < 0:
            raise ValueError("array bound must be a non-negative integer")
        return value
    resolved: Dict[str, TypeDef] = {}
    array_types: Dict[TypeId, TypeDef] = {}
    active = set()

    def resolve_name(name):
        canonical = TYPE_ALIASES.get(" ".join(name.split()), " ".join(name.split()))
        if canonical in primitive:
            return primitive[canonical]
        canonical = re.sub(r"^struct\s+", "", canonical)
        if canonical in resolved:
            return resolved[canonical]
        if canonical in active:
            raise ValueError("recursive struct composition")
        body = declarations.get(canonical)
        if body is None:
            raise ValueError(f"unknown or conflicting type {canonical}")
        active.add(canonical)
        try:
            fields = []
            offset = 0
            for raw in body.split(";"):
                raw = raw.strip()
                if not raw:
                    continue
                if any(token in raw for token in ("*", ":", "union", "{")):
                    raise ValueError(f"unsupported declarator in {canonical}")
                match = re.fullmatch(
                    r"((?:unsigned|signed)(?:\s+(?:char|short|int|long))?|struct\s+[A-Za-z_]\w*|[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*)\s+([A-Za-z_]\w*)(?:\s*\[\s*([^\]]+)\s*\])?",
                    raw,
                )
                if not match:
                    raise ValueError(f"unsupported field declaration: {raw}")
                type_text, field_name, count_text = match.groups()
                child = resolve_name(type_text)
                count = constant(count_text) if count_text else None
                field_type = child
                if count is not None:
                    array_id = TypeId(f"header:{canonical}:{field_name}:array")
                    field_type = TypeDef(array_id, f"{child.name}[{count}]", "array",
                                         (child.size or 0) * count, child.signed,
                                         child.id, array_count=count,
                                         evidence=(origins[canonical],))
                    array_types[field_type.id] = field_type
                if field_type.size is None:
                    raise ValueError(f"incomplete field type {type_text}")
                fields.append(Field(field_name, field_type.id, offset))
                offset += field_type.size
            result = TypeDef(TypeId("header:" + canonical), canonical, "struct",
                             offset, fields=tuple(fields), evidence=(origins[canonical],))
            resolved[canonical] = result
            return result
        finally:
            active.remove(canonical)

    for name in declarations:
        if declarations[name] is None:
            continue
        try:
            resolve_name(name)
        except ValueError as exc:
            diagnostics.append(Diagnostic("header.invalid-struct", "warning",
                f"{name}: {exc}", (origins[name],)))
    used_arrays = {field.type_id for value in resolved.values() for field in value.fields}
    values = tuple(resolved.values()) + tuple(
        value for id_, value in array_types.items() if id_ in used_arrays)
    return ParseResult(HeaderTypes(values, tuple(macros)), tuple(diagnostics))


__all__ = ["HeaderInput", "HeaderTypes", "parse_headers"]
