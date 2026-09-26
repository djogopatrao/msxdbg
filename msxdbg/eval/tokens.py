"""Expression-token contracts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple

@dataclass(frozen=True)
class Token:
    kind: str
    lexeme: str
    start: int
    end: int
    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("invalid token span")

class ExpressionSyntaxError(Exception):
    def __init__(self, message: str, start: int, end: int) -> None:
        super().__init__(message)
        self.start = start
        self.end = end

def tokenize(text: str) -> Tuple[Token, ...]:
    raise NotImplementedError("eval.tokenize is not implemented")

__all__ = ["ExpressionSyntaxError", "Token", "tokenize"]
