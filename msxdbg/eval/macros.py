"""Bounded token-level macro expansion contracts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence, Tuple
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext
from .tokens import Token
from .tokens import tokenize
from msxdbg.debuginfo.model import ResolutionStatus


class MacroExpansionError(Exception):
    pass

@dataclass(frozen=True)
class ExpansionLimits:
    max_depth: int = 32
    max_tokens: int = 4096

@dataclass(frozen=True)
class ExpandedTokens:
    tokens: Tuple[Token, ...]
    origins: Tuple[str, ...] = ()
    def __post_init__(self) -> None:
        object.__setattr__(self, "tokens", tuple(self.tokens))
        object.__setattr__(self, "origins", tuple(self.origins))

class MacroExpander:
    def expand(self, tokens: Sequence[Token], catalog: MacroCatalog, context: MacroContext, limits: ExpansionLimits) -> ExpandedTokens:
        if limits.max_depth < 1 or limits.max_tokens < 1:
            raise ValueError("macro limits must be positive")
        origins = []
        expanded = self._expand(tuple(tokens), catalog, context, limits, (), origins)
        if len(expanded) > limits.max_tokens:
            raise MacroExpansionError("macro expansion exceeds token limit")
        return ExpandedTokens(expanded, tuple(origins))

    def _expand(self, tokens, catalog, context, limits, stack, origins):
        if len(stack) >= limits.max_depth:
            raise MacroExpansionError("macro expansion exceeds depth limit: " + " -> ".join(stack))
        output = []
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.kind != "identifier" or token.lexeme in ("hex", "bin"):
                output.append(token); index += 1; continue
            resolution = catalog.lookup(token.lexeme, context)
            if resolution.status == ResolutionStatus.MISSING:
                output.append(token); index += 1; continue
            if resolution.status == ResolutionStatus.AMBIGUOUS:
                raise MacroExpansionError(f"ambiguous macro: {token.lexeme}")
            definition = resolution.candidates[0]
            if definition.name in stack:
                raise MacroExpansionError("macro expansion cycle: " + " -> ".join(stack + (definition.name,)))
            consumed = 1
            arguments = None
            if definition.parameters is not None:
                if index + 1 >= len(tokens) or tokens[index + 1].lexeme != "(":
                    output.append(token); index += 1; continue
                arguments, consumed = self._arguments(tokens, index + 1)
                consumed += 1
                if len(arguments) != len(definition.parameters):
                    raise MacroExpansionError(f"macro {definition.name} expects {len(definition.parameters)} arguments, got {len(arguments)}")
            replacement = self._replacement(definition, token, arguments)
            origins.append(f"{definition.origin.path}:{definition.origin.line or 0}:{definition.name}")
            replacement = self._expand(replacement, catalog, context, limits,
                                       stack + (definition.name,), origins)
            output.extend(replacement)
            if len(output) > limits.max_tokens:
                raise MacroExpansionError("macro expansion exceeds token limit")
            index += consumed
        return tuple(output)

    def _replacement(self, definition, invocation, arguments):
        mapping = {} if arguments is None else dict(zip(definition.parameters, arguments))
        output = []
        for macro_token in definition.replacement:
            if macro_token.lexeme in mapping:
                output.extend(mapping[macro_token.lexeme])
                continue
            parsed = tokenize(macro_token.lexeme)
            if len(parsed) != 1:
                raise MacroExpansionError(f"unsupported replacement token: {macro_token.lexeme}")
            item = parsed[0]
            output.append(Token(item.kind, item.lexeme, invocation.start, invocation.end))
        return tuple(output)

    def _arguments(self, tokens, opening):
        arguments = []; current = []; depth = 0; index = opening + 1
        if index < len(tokens) and tokens[index].lexeme == ")": return (), 2
        while index < len(tokens):
            token = tokens[index]
            if token.lexeme in ("(", "["): depth += 1
            elif token.lexeme in (")", "]"):
                if token.lexeme == ")" and depth == 0:
                    arguments.append(tuple(current))
                    return tuple(arguments), index - opening + 1
                depth -= 1
                if depth < 0: break
            if token.lexeme == "," and depth == 0:
                arguments.append(tuple(current)); current = []
            else:
                current.append(token)
            index += 1
        raise MacroExpansionError("unterminated macro invocation")

__all__ = ["ExpandedTokens", "ExpansionLimits", "MacroExpander", "MacroExpansionError"]
