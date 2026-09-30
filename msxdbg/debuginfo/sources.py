"""Source-file lookup and window contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from .diagnostics import Diagnostic, Origin
from .model import Resolution, ResolutionStatus, SourceSpan


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
        self._cache: Dict[Path, Tuple[int, int, Tuple[str, ...]]] = {}

    def locate(self, source: SourceSpan) -> Resolution[Path]:
        raw = Path(source.path)
        normalized = Path(source.normalized_path)
        levels = []
        if raw.is_absolute():
            levels.append((raw,))
        relative = normalized if not normalized.is_absolute() else Path(*normalized.parts[1:])
        levels.append(tuple(root / relative for root in self._source_roots))
        levels.append(tuple(directory / relative for directory in self._listing_directories))
        # Some listings retain a build-machine prefix. Component suffixes are
        # tried only beneath configured roots, never by textual suffix matching.
        parts = relative.parts
        if len(parts) > 1:
            levels.extend(
                tuple(root / Path(*parts[index:])
                      for root in self._source_roots + self._listing_directories)
                for index in range(1, len(parts))
            )
        for level in levels:
            candidates = tuple(sorted({path.resolve() for path in level if path.is_file()}, key=str))
            if candidates:
                status = ResolutionStatus.UNIQUE if len(candidates) == 1 else ResolutionStatus.AMBIGUOUS
                diagnostics = () if status == ResolutionStatus.UNIQUE else (
                    Diagnostic("source.ambiguous", "warning",
                               f"source path is ambiguous: {source.path}",
                               tuple(Origin(path, record_kind="source") for path in candidates)),
                )
                return Resolution(status, candidates, diagnostics)
        diagnostic = Diagnostic("source.not-found", "warning",
                                f"source file is unavailable: {source.path}")
        return Resolution(ResolutionStatus.MISSING, (), (diagnostic,))

    def read_window(
        self, source: SourceSpan, before: int, after: int
    ) -> SourceWindow:
        if before < 0 or after < 0:
            raise ValueError("source window sizes must not be negative")
        if source.line is None:
            raise ValueError("source window requires a focal line")
        resolution = self.locate(source)
        path = resolution.unique_or_none()
        if path is None:
            fallback = ((source.line, source.text),) if source.text is not None else ()
            return SourceWindow(Path(source.path), fallback, source.line, resolution.diagnostics)
        try:
            stat = path.stat()
            cached = self._cache.get(path)
            if cached is None or cached[:2] != (stat.st_mtime_ns, stat.st_size):
                lines = tuple(path.read_text(encoding="utf-8").splitlines())
                self._cache[path] = (stat.st_mtime_ns, stat.st_size, lines)
            else:
                lines = cached[2]
        except (OSError, UnicodeError) as exc:
            diagnostic = Diagnostic("source.unreadable", "warning", str(exc),
                                    (Origin(path, record_kind="source"),))
            fallback = ((source.line, source.text),) if source.text is not None else ()
            return SourceWindow(path, fallback, source.line,
                                resolution.diagnostics + (diagnostic,))
        start = max(1, source.line - before)
        end = min(len(lines), source.line + after)
        numbered = tuple((number, lines[number - 1]) for number in range(start, end + 1))
        diagnostics = resolution.diagnostics
        if source.line > len(lines):
            diagnostics += (Diagnostic("source.line-out-of-range", "warning",
                f"source line {source.line} exceeds file length {len(lines)}",
                (Origin(path, record_kind="source"),)),)
        return SourceWindow(path, numbered, source.line, diagnostics)

    def invalidate(self, path: Optional[Path] = None) -> None:
        if path is None:
            self._cache.clear()
            return
        self._cache.pop(Path(path).resolve(), None)


__all__ = ["SourceRepository", "SourceWindow"]
