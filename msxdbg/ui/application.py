"""Lifecycle runner shared by interactive and batch frontends."""

from __future__ import annotations

from typing import Sequence, TextIO

from .batch import BatchRunner
from .commands import CommandContext
from .repl import Repl


class CommandApplication:
    def __init__(self, repl: Repl | None = None,
                 batch: BatchRunner | None = None) -> None:
        self._repl = repl or Repl()
        self._batch = batch or BatchRunner()

    def run_shell(self, context: CommandContext, error_writer: TextIO) -> int:
        return self._with_cleanup(
            context, error_writer, lambda: self._repl.run(context)
        )

    def run_exec(self, commands: Sequence[str], context: CommandContext,
                 writer: TextIO, error_writer: TextIO) -> int:
        return self._with_cleanup(
            context, error_writer,
            lambda: self._batch.run(commands, context, writer),
        )

    @staticmethod
    def _with_cleanup(context: CommandContext, error_writer: TextIO, action) -> int:
        active_error = None
        status = 1
        try:
            status = action()
        except BaseException as error:
            active_error = error
            raise
        finally:
            try:
                report = context.session.close()
            except Exception as cleanup_error:
                if active_error is None:
                    raise
                error_writer.write(
                    f"cleanup error: {type(cleanup_error).__name__}: {cleanup_error}\n"
                )
            else:
                for error in report.errors:
                    error_writer.write(f"cleanup error: {error}\n")
                for remote_id in report.pending_ids:
                    error_writer.write(f"cleanup pending breakpoint: {remote_id}\n")
                for number in report.unknown_creations:
                    error_writer.write(f"cleanup uncertain breakpoint: {number}\n")
                if report.errors or report.pending_ids or report.unknown_creations:
                    status = 1
        return status


__all__ = ["CommandApplication"]
