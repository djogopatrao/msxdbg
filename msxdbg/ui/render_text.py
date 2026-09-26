from __future__ import annotations
from typing import Protocol
from .results import CommandResult
class Console(Protocol):
    def print(self, *objects: object) -> None: ...
class TextRenderer:
    def render(self, result: CommandResult, console: Console) -> None: raise NotImplementedError("TextRenderer.render is not implemented")
__all__ = ["Console", "TextRenderer"]
