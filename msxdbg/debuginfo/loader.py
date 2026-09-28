"""Project discovery and loading contracts."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Optional, Tuple

from .diagnostics import Diagnostic, Origin, ProjectLoadError
from .map_parser import parse_map
from .lst_parser import parse_lst
from .cdb_parser import parse_cdb
from ._reconcile import reconcile
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
        root = Path(spec.out)
        if not root.is_dir():
            raise _failure("load.missing-directory", "output directory does not exist", root)
        found = {".map": [], ".lst": [], ".cdb": []}
        def walk_error(error):
            raise error
        try:
            for directory, _, files in os.walk(root, onerror=walk_error, followlinks=False):
                for name in files:
                    path = Path(directory) / name
                    if path.suffix.lower() in found:
                        found[path.suffix.lower()].append(path)
        except OSError as exc:
            raise _failure("load.discovery-error", str(exc), root) from exc
        def ordered(paths):
            return tuple(sorted(set(Path(p) for p in paths), key=str))
        artifacts = ImageArtifacts(
            ordered(found[".map"] if spec.maps is None else spec.maps),
            ordered(found[".lst"]),
            ordered(found[".cdb"] if spec.cdbs is None else spec.cdbs),
        )
        for path in artifacts.maps + artifacts.listings + artifacts.cdbs:
            try:
                with path.open("rb"):
                    pass
            except OSError as exc:
                raise _failure("load.unreadable-artifact", str(exc), path) from exc
        return artifacts

    def load(self, spec: ProjectSpec) -> LoadedProject:
        ids = [image.id for image in spec.images]
        if len(ids) != len(set(ids)):
            raise ProjectLoadError("duplicate image ids", (
                Diagnostic("load.duplicate-image", "error", "image ids must be unique"),))
        if not ids:
            raise ProjectLoadError("project requires an image", (
                Diagnostic("load.no-images", "error", "project requires at least one image"),))
        images, diagnostics, listing_directories = [], [], []
        for image_spec in spec.images:
            artifacts = self.discover(image_spec)
            if not artifacts.maps:
                raise _failure("load.missing-map", "image requires a MAP artifact", Path(image_spec.out))
            image_diagnostics = []
            def parsed(paths, parser):
                results = []
                for path in paths:
                    try:
                        with path.open(encoding="utf-8") as stream:
                            result = parser(stream, path)
                    except (OSError, UnicodeError) as exc:
                        raise _failure("load.unreadable-artifact", str(exc), path) from exc
                    results.append(result.value)
                    image_diagnostics.extend(result.diagnostics)
                return results
            maps = parsed(artifacts.maps, parse_map)
            listings = parsed(artifacts.listings, parse_lst)
            cdbs = parsed(artifacts.cdbs, parse_cdb)
            if not any(data.symbols for data in maps):
                raise ProjectLoadError("MAP contains no usable symbols", tuple(image_diagnostics) + (
                    Diagnostic("load.empty-map", "error", "no usable public symbols"),))
            image = reconcile(image_spec.id, maps, listings, cdbs, image_diagnostics)
            images.append(image)
            diagnostics.extend(image.diagnostics)
            listing_directories.extend(path.parent for path in artifacts.listings)
        for path in spec.struct_headers:
            diagnostics.append(Diagnostic("load.headers-unavailable", "warning",
                "header type and macro parsing is not implemented; header was not loaded", (Origin(Path(path)),)))
        return LoadedProject(Project(tuple(images)),
            SourceRepository(spec.source_roots, tuple(sorted(set(listing_directories), key=str))),
            MacroCatalog(), tuple(diagnostics))


def _failure(code, message, path):
    return ProjectLoadError(message, (Diagnostic(code, "error", message, (Origin(path),)),))


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
