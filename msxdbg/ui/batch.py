from __future__ import annotations
from typing import Sequence, TextIO
from .commands import CommandContext
class BatchRunner:
    def run(self, commands: Sequence[str], context: CommandContext, writer: TextIO) -> int:
        raise NotImplementedError("BatchRunner.run is not implemented")
__all__ = ["BatchRunner"]
