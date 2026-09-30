"""Project discovery and loading contracts."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
from typing import Optional, Tuple

from .diagnostics import Diagnostic, Origin, ProjectLoadError
from .map_parser import parse_map
from .lst_parser import parse_lst
from .cdb_parser import parse_cdb
from ._reconcile import reconcile
from .index import ImageMapping, Project
from .macros import MacroCatalog
from .model import Field, ImageId, TypeId
from .sources import SourceRepository
from .header_parser import HeaderInput, parse_headers


@dataclass(frozen=True)
class ImageSpec:
    """Inputs or discovery root for one linked image."""

    id: ImageId
    out: Path
    maps: Optional[Tuple[Path, ...]] = None
    cdbs: Optional[Tuple[Path, ...]] = None
    mappings: Tuple[Tuple[int, str, Optional[str], Optional[str]], ...] = ()

    def __post_init__(self) -> None:
        if self.maps is not None:
            object.__setattr__(self, "maps", tuple(self.maps))
        if self.cdbs is not None:
            object.__setattr__(self, "cdbs", tuple(self.cdbs))
        object.__setattr__(self, "mappings", tuple(self.mappings))


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
        header_inputs = []
        for path in spec.struct_headers:
            try:
                header_inputs.append(HeaderInput(Path(path), Path(path).read_text(encoding="utf-8")))
            except (OSError, UnicodeError) as exc:
                diagnostics.append(Diagnostic("load.header-unreadable", "warning",
                    str(exc), (Origin(Path(path)),)))
        header_result = parse_headers(header_inputs)
        diagnostics.extend(header_result.diagnostics)
        if header_result.value.types:
            updated = []
            for image in images:
                id_map = {item.id: TypeId(item.id.record_identity, image.id)
                          for item in header_result.value.types}
                header_types = tuple(replace(item, id=id_map[item.id],
                    referenced_type=id_map.get(item.referenced_type, item.referenced_type),
                    fields=tuple(Field(field.name, id_map.get(field.type_id, field.type_id), field.offset)
                                 for field in item.fields))
                    for item in header_result.value.types)
                existing_names = {item.name for item in image.types if item.category != "incomplete"}
                accepted = tuple(item for item in header_types if item.name not in existing_names)
                for item in header_types:
                    if item.name in existing_names:
                        diagnostics.append(Diagnostic("load.header-type-shadowed", "warning",
                            f"CDB type takes precedence over header type {item.name}", item.evidence))
                updated.append(replace(image, types=image.types + accepted))
            images = updated
        mappings = tuple(ImageMapping(spec.id, *mapping)
                         for spec in spec.images for mapping in spec.mappings)
        return LoadedProject(Project(tuple(images), mappings),
            SourceRepository(spec.source_roots, tuple(sorted(set(listing_directories), key=str))),
            MacroCatalog(header_result.value.macros), tuple(diagnostics))


def _failure(code, message, path):
    return ProjectLoadError(message, (Diagnostic(code, "error", message, (Origin(path),)),))


def read_project_spec(path: Path) -> ProjectSpec:
    """Read the version-1 JSON project manifest without performing target I/O."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _failure("project.invalid-json", str(exc), path) from exc
    if (not isinstance(raw, dict) or type(raw.get("version")) is not int
            or raw.get("version") != 1):
        raise _failure("project.unsupported-version",
                       "project manifest version must be 1", path)
    allowed = {"version", "images", "source_roots", "struct_headers"}
    unknown = set(raw) - allowed
    if unknown:
        raise _failure("project.unknown-field",
                       "unknown project fields: " + ", ".join(sorted(unknown)), path)
    if not isinstance(raw.get("images"), list) or not raw["images"]:
        raise _failure("project.invalid-images", "images must be a non-empty array", path)
    base = path.resolve().parent
    def paths(value, field):
        if value is None:
            return None
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise _failure("project.invalid-field", f"{field} must be an array of paths", path)
        return tuple((base / item).resolve() if not Path(item).is_absolute()
                     else Path(item).resolve() for item in value)
    images = []
    for index, item in enumerate(raw["images"]):
        if not isinstance(item, dict) or set(item) - {"id", "out", "maps", "cdbs", "mappings"}:
            raise _failure("project.invalid-image", f"invalid image at index {index}", path)
        if (not isinstance(item.get("id"), str) or not item["id"]
                or not isinstance(item.get("out"), str) or not item["out"]):
            raise _failure("project.invalid-image", f"image {index} requires string id and out", path)
        out = Path(item["out"])
        out = (base / out).resolve() if not out.is_absolute() else out.resolve()
        raw_mappings = item.get("mappings", [])
        if not isinstance(raw_mappings, list):
            raise _failure("project.invalid-mappings", "mappings must be an array", path)
        mappings = []
        for mapping in raw_mappings:
            if not isinstance(mapping, dict) or set(mapping) - {"page", "slot", "segment"}:
                raise _failure("project.invalid-mapping", "invalid image mapping", path)
            page, slot, segment = mapping.get("page"), mapping.get("slot"), mapping.get("segment")
            if type(page) is not int or page not in range(4) or not isinstance(slot, str):
                raise _failure("project.invalid-mapping", "mapping requires page 0..3 and slot string", path)
            fields = slot.split(".")
            if len(fields) not in (1, 2) or fields[0] not in ("0", "1", "2", "3") \
                    or len(fields) == 2 and fields[1] not in ("0", "1", "2", "3", "X"):
                raise _failure("project.invalid-mapping", "mapping slot expects P or P.S", path)
            if segment is not None and (type(segment) is not int or segment < 0):
                raise _failure("project.invalid-mapping", "mapping segment must be non-negative", path)
            mappings.append((page, fields[0], fields[1] if len(fields) == 2 else None,
                             str(segment) if segment is not None else None))
        images.append(ImageSpec(ImageId(item["id"]), out,
                                paths(item.get("maps"), "maps"),
                                paths(item.get("cdbs"), "cdbs"), tuple(mappings)))
    return ProjectSpec(tuple(images), paths(raw.get("source_roots", []), "source_roots") or (),
                       paths(raw.get("struct_headers", []), "struct_headers") or ())


__all__ = [
    "ImageArtifacts",
    "ImageSpec",
    "LoadedProject",
    "ProjectLoader",
    "ProjectSpec",
    "read_project_spec",
]
