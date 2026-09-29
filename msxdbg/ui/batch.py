from __future__ import annotations
from dataclasses import dataclass
from time import monotonic
from typing import Callable, Sequence, TextIO
from .commands import CommandContext, CommandDispatcher
from .render_json import JsonRenderer
from .results import CommandError, CommandResult

class _DeadlineCancellation:
    def __init__(self, clock: Callable[[], float], deadline: float) -> None:
        self._clock = clock; self._deadline = deadline
    def is_cancelled(self) -> bool:
        return self._clock() >= self._deadline

@dataclass(frozen=True)
class BatchPolicy:
    """Stable execution policy for the non-interactive command runner."""
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("batch timeout must be positive")

class BatchRunner:
    def __init__(self, dispatcher: CommandDispatcher | None = None,
                 renderer: JsonRenderer | None = None,
                 policy: BatchPolicy | None = None,
                 clock: Callable[[], float] = monotonic) -> None:
        self._dispatcher = dispatcher or CommandDispatcher()
        self._renderer = renderer or JsonRenderer()
        self._policy = policy or BatchPolicy()
        self._clock = clock

    def run(self, commands: Sequence[str], context: CommandContext, writer: TextIO) -> int:
        deadline = self._clock() + self._policy.timeout_seconds
        previous_timeout = context.execution_timeout
        previous_cancellation = context.cancellation
        previous_origin = context.input_origin
        context.input_origin = "batch"
        context.cancellation = _DeadlineCancellation(self._clock, deadline)
        try:
            for index, command in enumerate(commands):
                name = command.strip().partition(" ")[0]
                remaining = deadline - self._clock()
                context.execution_timeout = max(0.0, remaining)
                specification = self._dispatcher.specification(command)
                if remaining <= 0:
                    result = self._timeout(name)
                elif (name == "clear" or
                      specification is not None and specification.confirmation is not None):
                    result = CommandResult(name, False, error=CommandError(
                        "command-not-available-in-batch",
                        f"{name} is not available in batch execution",
                        {"command": name},
                    ))
                else:
                    try:
                        result = self._dispatcher.dispatch(command, context)
                    except Exception as error:
                        result = CommandResult(name, False, error=CommandError(
                            "internal-error", str(error),
                            {"error_type": type(error).__name__}))
                    if result.ok and self._clock() >= deadline:
                        result = self._timeout(name)
                writer.write(self._renderer.encode(result, index))
                writer.write("\n")
                if not result.ok:
                    return 1
            return 0
        finally:
            context.execution_timeout = previous_timeout
            context.cancellation = previous_cancellation
            context.input_origin = previous_origin

    def _timeout(self, command: str) -> CommandResult:
        return CommandResult(command, False, error=CommandError(
            "batch-timeout",
            f"batch deadline of {self._policy.timeout_seconds:g} seconds exceeded",
            {"timeout_seconds": self._policy.timeout_seconds},
        ))

__all__ = ["BatchPolicy", "BatchRunner"]
