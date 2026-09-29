from __future__ import annotations
from typing import Callable, Optional
from .commands import CommandContext, CommandDispatcher
from .render_text import Console, TextRenderer
from .results import UiAction

class _StdoutConsole:
    def print(self, *objects: object) -> None:
        print(*objects)

class Repl:
    def __init__(self, dispatcher: Optional[CommandDispatcher] = None,
                 renderer: Optional[TextRenderer] = None,
                 reader: Callable[[str], str] = input,
                 console: Optional[Console] = None) -> None:
        self._dispatcher = dispatcher or CommandDispatcher()
        self._renderer = renderer or TextRenderer()
        self._reader = reader
        self._console = console or _StdoutConsole()

    def run(self, context: CommandContext) -> int:
        context.input_origin = "interactive"
        previous = None
        while True:
            try:
                text = self._reader("msxdbg> ")
            except EOFError:
                return 0
            except KeyboardInterrupt:
                self._console.print("^C")
                continue
            stripped = text.strip()
            if not stripped:
                if previous is None:
                    continue
                stripped = previous
            try:
                result = self._dispatcher.dispatch(stripped, context)
            except KeyboardInterrupt:
                self._console.print("^C")
                continue
            self._renderer.render(result, self._console)
            if result.ok and isinstance(result.payload, UiAction):
                if result.payload.action == UiAction.QUIT:
                    return 0
                if result.payload.action == UiAction.CLEAR:
                    self._console.print("\x1b[H\x1b[2J\x1b[3J")
            specification = self._dispatcher.specification(stripped)
            if result.ok and specification is not None and specification.repeatable:
                previous = stripped

__all__ = ["Repl"]
