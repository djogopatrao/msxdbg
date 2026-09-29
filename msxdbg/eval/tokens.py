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
    tokens = []
    index = 0
    single = set("+-*/%&|^~()[],")
    while index < len(text):
        char = text[index]
        if char.isspace():
            index += 1
            continue
        start = index
        if text.startswith(("<<", ">>"), index):
            index += 2
            tokens.append(Token("operator", text[start:index], start, index))
        elif char in single:
            index += 1
            kind = "operator" if char in "+-*/%&|^~" else "punctuation"
            tokens.append(Token(kind, char, start, index))
        elif char == "#":
            index += 1
            while index < len(text) and text[index] in "0123456789abcdefABCDEF":
                index += 1
            if index == start + 1:
                raise ExpressionSyntaxError("expected hexadecimal digits", start, index)
            tokens.append(Token("number", text[start:index], start, index))
        elif char.isdigit():
            index += 1
            if char == "0" and index < len(text) and text[index] in "xX":
                index += 1
                digit_start = index
                while index < len(text) and text[index] in "0123456789abcdefABCDEF":
                    index += 1
                if index == digit_start:
                    raise ExpressionSyntaxError("expected hexadecimal digits", start, index)
            else:
                while index < len(text) and text[index].isdigit():
                    index += 1
            tokens.append(Token("number", text[start:index], start, index))
        elif char.isalpha() or char == "_":
            index += 1
            while index < len(text) and (text[index].isalnum() or text[index] in "_':"):
                index += 1
            tokens.append(Token("identifier", text[start:index], start, index))
        else:
            raise ExpressionSyntaxError(f"unexpected character {char!r}", start, start + 1)
    return tuple(tokens)

__all__ = ["ExpressionSyntaxError", "Token", "tokenize"]
