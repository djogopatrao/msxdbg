from __future__ import annotations
from .results import CommandResult
class JsonRenderer:
    def encode(self, result: CommandResult, command_index: int) -> str: raise NotImplementedError("JsonRenderer.encode is not implemented")
__all__ = ["JsonRenderer"]
