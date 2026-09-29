"""Expression and print-request parser contracts."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from .ast import Binary, BuiltinCall, Expr, Group, Index, Indirect, Name, Number, Unary
from .macros import ExpandedTokens
from .tokens import ExpressionSyntaxError, Token, tokenize

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
        self._tokens = tokenize(text)
        self._position = 0
        if not self._tokens:
            raise ExpressionSyntaxError("empty expression", 0, 0)
        expression = self._parse_binary(0)
        if self._position != len(self._tokens):
            token = self._tokens[self._position]
            raise ExpressionSyntaxError("unexpected token", token.start, token.end)
        return expression

    def parse_print(self, arguments: ExpandedTokens, type_name: Optional[str] = None) -> PrintRequest:
        text = "".join(token.lexeme for token in arguments.tokens)
        expression = self.parse_expression(text)
        mode = (EvaluationMode.READ_MEMORY if type_name is not None or isinstance(expression, Indirect)
                else EvaluationMode.INSPECT_VARIABLE if isinstance(expression, Name)
                else EvaluationMode.CALCULATE)
        if type_name is not None and isinstance(expression, BuiltinCall):
            raise ExpressionSyntaxError("display builtin cannot be combined with a memory type", 0, len(text))
        return PrintRequest(expression, mode, type_name, text)

    def _peek(self, lexeme=None):
        if self._position >= len(self._tokens): return None
        token = self._tokens[self._position]
        return token if lexeme is None or token.lexeme == lexeme else None

    def _take(self):
        token = self._tokens[self._position]; self._position += 1; return token

    def _expect(self, lexeme):
        token = self._peek(lexeme)
        if token is None:
            position = self._tokens[-1].end if self._tokens else 0
            raise ExpressionSyntaxError(f"expected {lexeme!r}", position, position)
        return self._take()

    def _parse_binary(self, minimum):
        left = self._parse_prefix()
        precedence = {"|":1,"^":2,"&":3,"<<":4,">>":4,"+":5,"-":5,"*":6,"/":6,"%":6}
        while self._peek() is not None and self._peek().lexeme in precedence and precedence[self._peek().lexeme] >= minimum:
            operator = self._take().lexeme
            right = self._parse_binary(precedence[operator] + 1)
            left = Binary(left, operator, right)
        return left

    def _parse_prefix(self):
        token = self._peek()
        if token is None:
            position = self._tokens[-1].end if self._tokens else 0
            raise ExpressionSyntaxError("expected expression", position, position)
        if token.lexeme in ("+", "-", "~"):
            self._take(); return Unary(token.lexeme, self._parse_prefix())
        if token.lexeme == "(":
            self._take(); expression = Group(self._parse_binary(0)); self._expect(")")
        elif token.lexeme == "[":
            self._take(); expression = Indirect(self._parse_binary(0), "u8"); self._expect("]")
        elif token.kind == "number":
            self._take(); expression = Number(int(token.lexeme[1:] if token.lexeme.startswith("#") else token.lexeme, 16 if token.lexeme.startswith(("#","0x","0X")) else 10))
        elif token.kind == "identifier":
            self._take()
            if self._peek("("):
                if token.lexeme not in ("hex", "bin"):
                    raise ExpressionSyntaxError("only hex() and bin() calls are supported", token.start, token.end)
                self._take(); arguments=[]
                if not self._peek(")"):
                    arguments.append(self._parse_binary(0))
                    while self._peek(","):
                        self._take(); arguments.append(self._parse_binary(0))
                self._expect(")"); expression=BuiltinCall(token.lexeme, tuple(arguments))
            else:
                expression = Name(token.lexeme)
        else:
            raise ExpressionSyntaxError("expected expression", token.start, token.end)
        while self._peek("["):
            self._take(); index=self._parse_binary(0); self._expect("]"); expression=Index(expression,index)
        return expression

__all__ = ["EvaluationMode", "ExpressionParser", "PrintRequest"]
