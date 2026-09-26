"""Typed diagnostics shared by the offline debug-information layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Optional, Sequence, Tuple, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class Origin:
    """Physical origin of a parsed record or diagnostic."""

    path: Path
    line: Optional[int] = None
    record_kind: str = "unknown"

    def __post_init__(self) -> None:
        if self.line is not None and self.line < 1:
            raise ValueError("origin line must be positive")
        if not self.record_kind:
            raise ValueError("origin record_kind must not be empty")


@dataclass(frozen=True)
class Diagnostic:
    """Structured parse or reconciliation diagnostic."""

    code: str
    severity: str
    message: str
    origins: Tuple[Origin, ...] = ()

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("diagnostic code must not be empty")
        if not self.severity:
            raise ValueError("diagnostic severity must not be empty")
        object.__setattr__(self, "origins", tuple(self.origins))


@dataclass(frozen=True)
class ParseResult(Generic[T]):
    """A parsed value together with every non-fatal diagnostic."""

    value: T
    diagnostics: Tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


class ProjectLoadError(Exception):
    """Raised when project loading cannot produce a usable project."""

    def __init__(
        self,
        message: str,
        diagnostics: Sequence[Diagnostic] = (),
    ) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)


__all__ = ["Diagnostic", "Origin", "ParseResult", "ProjectLoadError"]
