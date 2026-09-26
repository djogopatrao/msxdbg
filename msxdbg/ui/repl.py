from __future__ import annotations
from .commands import CommandContext
class Repl:
    def run(self, context: CommandContext) -> int: raise NotImplementedError("Repl.run is not implemented")
__all__ = ["Repl"]
