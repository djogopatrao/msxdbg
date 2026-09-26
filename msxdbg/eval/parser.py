"""Expression and print-request parser contracts."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from .ast import Expr
from .macros import ExpandedTokens

class EvaluationMode(str, Enum):
    CALCULATE = "calculate"
    READ_MEMORY = "read-memory"
    INSPECT_VARIABLE = "inspect-variable"

@dataclass(frozen=True)
class PrintRequest:
    expression: Expr
    mode: EvaluationMode
    type_name: Optional[str] = None
    original_text: str = ""

class ExpressionParser:
    def parse_expression(self, text: str) -> Expr:
        raise NotImplementedError("ExpressionParser.parse_expression is not implemented")
    def parse_print(self, arguments: ExpandedTokens, type_name: Optional[str] = None) -> PrintRequest:
        raise NotImplementedError("ExpressionParser.parse_print is not implemented")

__all__ = ["EvaluationMode", "ExpressionParser", "PrintRequest"]
