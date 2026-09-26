"""Immutable expression AST contracts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple

class Expr: pass

@dataclass(frozen=True)
class Number(Expr): value: int
@dataclass(frozen=True)
class Name(Expr): value: str
@dataclass(frozen=True)
class Unary(Expr): operator: str; operand: Expr
@dataclass(frozen=True)
class Binary(Expr): left: Expr; operator: str; right: Expr
@dataclass(frozen=True)
class Group(Expr): expression: Expr
@dataclass(frozen=True)
class Indirect(Expr): address: Expr; type_name: str
@dataclass(frozen=True)
class Index(Expr): expression: Expr; index: Expr
@dataclass(frozen=True)
class BuiltinCall(Expr):
    name: str
    arguments: Tuple[Expr, ...]
    def __post_init__(self) -> None: object.__setattr__(self, "arguments", tuple(self.arguments))

__all__ = ["Binary", "BuiltinCall", "Expr", "Group", "Index", "Indirect", "Name", "Number", "Unary"]
