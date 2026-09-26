"""Source-file lookup and window contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .diagnostics import Diagnostic
from .model import Resolution, SourceSpan


@dataclass(frozen=True)
class SourceWindow:
    """Numbered source lines surrounding one focal line."""

    path: Path
    lines: Tuple[Tuple[int, str], ...]
    focal_line: int
    diagnostics: Tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "lines", tuple(self.lines))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


class SourceRepository:
    """Source locator with a cache independent of target stop state."""

    def __init__(
        self,
        source_roots: Sequence[Path] = (),
        listing_directories: Sequence[Path] = (),
    ) -> None:
        self._source_roots = tuple(source_roots)
        self._listing_directories = tuple(listing_directories)

    def locate(self, source: SourceSpan) -> Resolution[Path]:
        raise NotImplementedError("SourceRepository.locate is not implemented")

    def read_window(
        self, source: SourceSpan, before: int, after: int
    ) -> SourceWindow:
        raise NotImplementedError("SourceRepository.read_window is not implemented")

    def invalidate(self, path: Optional[Path] = None) -> None:
        raise NotImplementedError("SourceRepository.invalidate is not implemented")


__all__ = ["SourceRepository", "SourceWindow"]
