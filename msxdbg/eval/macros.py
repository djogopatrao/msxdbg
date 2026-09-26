"""Bounded token-level macro expansion contracts."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence, Tuple
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext
from .tokens import Token

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
        raise NotImplementedError("MacroExpander.expand is not implemented")

__all__ = ["ExpandedTokens", "ExpansionLimits", "MacroExpander"]
