from __future__ import annotations
from pathlib import Path
import os
from typing import Callable, Optional
from .commands import CommandContext, CommandDispatcher
from .render_text import Console, TextRenderer
from .results import UiAction

class _StdoutConsole:
    def print(self, *objects: object) -> None:
        print(*objects)


class _ReadlineReader:
    """Optional stdlib line editing, history and contextual completion."""
    def __init__(self, dispatcher: CommandDispatcher, context: CommandContext,
                 history_limit: int = 1000, history_path: Optional[Path] = None) -> None:
        self._dispatcher = dispatcher
        self._context = context
        self._limit = history_limit
        self._path = history_path or self._default_history_path()
        self._readline = None
        self._matches = []
        try:
            import readline
            self._readline = readline
            readline.set_history_length(history_limit)
            readline.parse_and_bind("tab: complete")
            readline.set_completer_delims(" \t\n")
            readline.set_completer(self._complete)
            if hasattr(readline, "set_auto_history"):
                readline.set_auto_history(False)
            try: readline.read_history_file(str(self._path))
            except OSError: pass
        except (ImportError, RuntimeError):
            self._readline = None

    @staticmethod
    def _default_history_path() -> Path:
        state = os.environ.get("XDG_STATE_HOME")
        root = Path(state) if state else Path.home() / ".local" / "state"
        return root / "msxdbg" / "history"

    def _complete(self, _fragment: str, state: int):
        assert self._readline is not None
        if state == 0:
            text = self._readline.get_line_buffer()
            cursor = self._readline.get_endidx()
            self._matches = [item.value for item in
                self._dispatcher.complete(text, cursor, self._context)]
        return self._matches[state] if state < len(self._matches) else None

    def __call__(self, prompt: str) -> str:
        text = input(prompt)
        if self._readline is not None and text.strip():
            count = self._readline.get_current_history_length()
            previous = self._readline.get_history_item(count) if count else None
            if previous != text:
                self._readline.add_history(text)
        return text

    def close(self) -> None:
        if self._readline is None:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._readline.set_history_length(self._limit)
            self._readline.write_history_file(str(self._path))
        except OSError:
            pass

class Repl:
    def __init__(self, dispatcher: Optional[CommandDispatcher] = None,
                 renderer: Optional[TextRenderer] = None,
                 reader: Optional[Callable[[str], str]] = None,
                 console: Optional[Console] = None) -> None:
        self._dispatcher = dispatcher or CommandDispatcher()
        self._renderer = renderer or TextRenderer()
        self._reader = reader
        self._console = console or _StdoutConsole()

    def run(self, context: CommandContext) -> int:
        context.input_origin = "interactive"
        reader = self._reader or _ReadlineReader(self._dispatcher, context)
        previous = None
        try:
            while True:
                try:
                    text = reader("msxdbg> ")
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
        finally:
            close = getattr(reader, "close", None)
            if close is not None:
                close()

__all__ = ["Repl"]
