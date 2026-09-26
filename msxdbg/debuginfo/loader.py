"""Project discovery and loading contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .diagnostics import Diagnostic
from .index import Project
from .macros import MacroCatalog
from .model import ImageId
from .sources import SourceRepository


@dataclass(frozen=True)
class ImageSpec:
    """Inputs or discovery root for one linked image."""

    id: ImageId
    out: Path
    maps: Optional[Tuple[Path, ...]] = None
    cdbs: Optional[Tuple[Path, ...]] = None

    def __post_init__(self) -> None:
        if self.maps is not None:
            object.__setattr__(self, "maps", tuple(self.maps))
        if self.cdbs is not None:
            object.__setattr__(self, "cdbs", tuple(self.cdbs))


@dataclass(frozen=True)
class ProjectSpec:
    """Stable internal configuration for all project images."""

    images: Tuple[ImageSpec, ...]
    source_roots: Tuple[Path, ...] = ()
    struct_headers: Tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "images", tuple(self.images))
        object.__setattr__(self, "source_roots", tuple(self.source_roots))
        object.__setattr__(self, "struct_headers", tuple(self.struct_headers))


@dataclass(frozen=True)
class ImageArtifacts:
    """Artifact paths discovered for one image, separated by kind."""

    maps: Tuple[Path, ...] = ()
    listings: Tuple[Path, ...] = ()
    cdbs: Tuple[Path, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "maps", tuple(self.maps))
        object.__setattr__(self, "listings", tuple(self.listings))
        object.__setattr__(self, "cdbs", tuple(self.cdbs))


@dataclass(frozen=True)
class LoadedProject:
    """Offline services and diagnostics produced by project loading."""

    project: Project
    sources: SourceRepository
    macros: MacroCatalog
    diagnostics: Tuple[Diagnostic, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))


class ProjectLoader:
    """Discover, parse, reconcile, and index project artifacts."""

    def discover(self, spec: ImageSpec) -> ImageArtifacts:
        raise NotImplementedError("ProjectLoader.discover is not implemented")

    def load(self, spec: ProjectSpec) -> LoadedProject:
        raise NotImplementedError("ProjectLoader.load is not implemented")


def read_project_spec(path: Path) -> ProjectSpec:
    """Read an external project manifest once its schema is stabilized."""

    raise NotImplementedError("debuginfo.read_project_spec is not implemented")


__all__ = [
    "ImageArtifacts",
    "ImageSpec",
    "LoadedProject",
    "ProjectLoader",
    "ProjectSpec",
    "read_project_spec",
]
