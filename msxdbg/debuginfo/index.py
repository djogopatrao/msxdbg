"""Immutable project-query contracts for offline debug information."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional, Tuple

from .model import (
    CodeLocation,
    Function,
    FunctionId,
    Image,
    ImageId,
    ModuleId,
    Resolution,
    Symbol,
    TypeDef,
    TypeId,
    Variable,
    ResolutionStatus,
)


CODE_AREAS = frozenset(("_CODE", "_HOME", "_GSINIT", "_GSFINAL"))


@dataclass(frozen=True)
class LineMatch:
    requested_line: int
    effective_line: int
    location: CodeLocation


@dataclass(frozen=True)
class SymbolMatch:
    symbol: Symbol
    offset: int


@dataclass(frozen=True)
class SymbolContext:
    image: Optional[ImageId]
    module: Optional[ModuleId]
    function: Optional[FunctionId]
    pc: int


@dataclass(frozen=True)
class ImageMapping:
    image: ImageId
    page: int
    primary_slot: str
    secondary_slot: Optional[str] = None
    segment: Optional[str] = None

    def __post_init__(self) -> None:
        if self.page not in (0, 1, 2, 3):
            raise ValueError("mapping page must be between 0 and 3")
        if self.primary_slot not in ("0", "1", "2", "3"):
            raise ValueError("mapping primary slot must be 0..3")
        if self.secondary_slot is not None and self.secondary_slot not in ("0", "1", "2", "3", "X"):
            raise ValueError("mapping secondary slot must be 0..3 or X")


class VariableKind:
    LOCALS = "locals"
    PARAMETERS = "parameters"
    ALL = "all"


@dataclass(frozen=True)
class CompletionCatalog:
    symbols: Tuple[str, ...] = ()
    types: Tuple[str, ...] = ()
    files: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for attribute in ("symbols", "types", "files"):
            object.__setattr__(self, attribute, tuple(getattr(self, attribute)))


@dataclass(frozen=True)
class Project:
    """Read-only query facade over all loaded images."""

    images: Tuple[Image, ...]
    mappings: Tuple[ImageMapping, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "images", tuple(self.images))
        object.__setattr__(self, "mappings", tuple(self.mappings))
        if len({item.id for item in self.images}) != len(self.images):
            raise ValueError("duplicate image ids")
        if any(item.image not in {image.id for image in self.images} for item in self.mappings):
            raise ValueError("mapping refers to an unknown image")

    def image_for_pages(self, pages, address: int) -> Optional[ImageId]:
        page = address // 0x4000
        observed = next((item for item in pages if item.page == page), None)
        if observed is None:
            return None
        matches = {item.image for item in self.mappings
                   if item.page == page and item.primary_slot == observed.primary_slot
                   and (item.secondary_slot is None or item.secondary_slot == observed.secondary_slot)
                   and (item.segment is None or item.segment == observed.segment)}
        return next(iter(matches)) if len(matches) == 1 else None

    def _images(self, image):
        return tuple(item for item in self.images if image is None or item.id == image)

    def _result(self, candidates, image=None):
        candidates = tuple(candidates)
        status = (ResolutionStatus.MISSING if not candidates else
                  ResolutionStatus.UNIQUE if len(candidates) == 1 else ResolutionStatus.AMBIGUOUS)
        diagnostics = tuple(d for item in self._images(image) for d in item.diagnostics)
        return Resolution(status, candidates, diagnostics)

    def _locations(self, image=None):
        for item in self._images(image):
            cdb = list(item.locations) + [x for f in item.functions for x in f.locations]
            seen = set()
            for location in cdb:
                key = (location.module, location.address, location.source)
                if key not in seen:
                    seen.add(key)
                    yield location
            cdb_addresses = {x.address for x in cdb}
            for module in item.modules:
                yield from (x for x in module.locations if x.address not in cdb_addresses)

    def _context_functions(self, context):
        _address(context.pc)
        if context.module and context.image and context.module.image != context.image:
            raise ValueError("context module belongs to a different image")
        if context.function and ((context.image and context.function.module.image != context.image)
                                 or (context.module and context.function.module != context.module)):
            raise ValueError("context function belongs to a different module/image")
        return tuple(f for f in self.function_at(context.pc, context.image).candidates
                     if (context.module is None or f.id.module == context.module)
                     and (context.function is None or f.id == context.function))

    def resolve(
        self, address: int, image: Optional[ImageId] = None
    ) -> Resolution[CodeLocation]:
        _address(address)
        candidates = []
        functions = self.function_at(address, image).candidates
        for item in self._images(image):
            for module in item.modules:
                areas = [a for a in module.areas if a.name in CODE_AREAS and a.base is not None
                         and a.limit is not None and a.base <= address < a.limit]
                owned = [f for f in functions if f.id.module == module.id]
                if not areas and not owned:
                    continue
                choices = owned or [None]
                for function in choices:
                    cdb_locations = tuple(x for x in item.locations if x.module == module.id)
                    locations = function.locations if function and function.locations else cdb_locations + module.locations
                    known = [x for x in locations if x.address <= address and x.source is not None
                             and (function is None or x.address >= function.entry)]
                    source = max(known, key=lambda x: x.address) if known else None
                    base = areas[0].base if areas else function.entry
                    evidence = tuple(o for a in areas for o in a.evidence)
                    if function:
                        evidence += function.evidence
                    if source:
                        evidence += source.evidence
                    area_name = areas[0].name if areas else next(
                        (x.area for x in locations if x.address == address), "_CODE")
                    candidates.append(CodeLocation(item.id, address, module.id, area_name,
                        address - base, source.source if source else None,
                        function.id if function else None, evidence))
        if not candidates:
            candidates = [x for x in self._locations(image) if x.address == address]
        return self._result(candidates, image)

    def resolve_line(
        self, path: str, line: int, image: Optional[ImageId] = None
    ) -> Resolution[LineMatch]:
        if line < 1 or not path:
            raise ValueError("source path and positive line required")
        requested = _path_parts(path)
        groups = {}
        for location in self._locations(image):
            source = location.source
            if source is None or source.line is None:
                continue
            parts = _path_parts(source.normalized_path)
            if len(parts) < len(requested) or parts[-len(requested):] != requested:
                continue
            key = (location.image, location.module, parts)
            groups.setdefault(key, []).append(location)
        candidates = []
        for locations in groups.values():
            following = [x for x in locations if x.source.line >= line]
            if following:
                selected = min(following, key=lambda x: (x.source.line, x.address))
                candidates.append(LineMatch(line, selected.source.line, selected))
        # CDB and listing reconciliation can expose the same source/address
        # through more than one module record.  That is supporting evidence,
        # not a user-visible ambiguity.
        unique = {}
        for candidate in candidates:
            source = candidate.location.source
            key = (candidate.location.image, candidate.location.address,
                   source.normalized_path if source is not None else None,
                   candidate.effective_line)
            unique.setdefault(key, candidate)
        return self._result(unique.values(), image)

    def lookup_symbol(
        self, name: str, image: Optional[ImageId] = None
    ) -> Resolution[Symbol]:
        symbols = []
        seen = set()
        for item in self._images(image):
            for symbol in item.symbols + tuple(s for m in item.modules for s in m.labels):
                key = (symbol.name, symbol.address, symbol.module)
                if key not in seen:
                    seen.add(key)
                    symbols.append(symbol)
        exact = [s for s in symbols if s.name == name]
        aliases = [s for s in symbols if s.name.startswith("_") and s.name[1:] == name]
        return self._result(exact or aliases, image)

    def is_listing_only_symbol(self, symbol: Symbol) -> bool:
        image = next((item for item in self.images if item.id == symbol.module.image), None) \
            if symbol.module is not None else None
        if image is None:
            return False
        return not any((item.name, item.address, item.module) ==
                       (symbol.name, symbol.address, symbol.module) for item in image.symbols)

    def nearest_symbol(
        self, address: int, image: Optional[ImageId] = None
    ) -> Resolution[SymbolMatch]:
        _address(address)
        symbols = [s for item in self._images(image) for s in item.symbols if s.address <= address]
        if not symbols:
            return self._result((), image)
        nearest = max(s.address for s in symbols)
        return self._result((SymbolMatch(s, address - s.address) for s in symbols
                             if s.address == nearest), image)

    def function_at(
        self, address: int, image: Optional[ImageId] = None
    ) -> Resolution[Function]:
        _address(address)
        return self._result((f for item in self._images(image) for f in item.functions
            if (f.entry <= address < f.end if f.end is not None else
                address == f.entry or any(x.address == address for x in f.locations))), image)

    def find_variable(
        self, name: str, context: SymbolContext
    ) -> Resolution[Variable]:
        functions = self._context_functions(context)
        locals_ = []
        for function in functions:
            local_context = SymbolContext(function.id.module.image, function.id.module, function.id, context.pc)
            visible = [v for v in self.variables_in_scope(local_context, VariableKind.ALL) if v.name == name]
            if visible:
                level = max(v.level or 0 for v in visible)
                locals_.extend(v for v in visible if (v.level or 0) == level)
        if locals_:
            return self._result(locals_, context.image)
        module = context.module or (context.function.module if context.function else None)
        if module is None and len(functions) == 1:
            module = functions[0].id.module
        image = context.image or (module.image if module else None)
        variables = [v for item in self._images(image) for v in item.variables
                     if v.function is None and v.name == name]
        statics = [v for v in variables if v.scope == "static"
                   and (module is None or v.id.module == module)]
        globals_ = [v for v in variables if v.scope == "global"]
        return self._result((statics or globals_) if module else statics + globals_, image)

    def variables_in_scope(
        self, context: SymbolContext, kind: str
    ) -> Tuple[Variable, ...]:
        if kind not in (VariableKind.ALL, VariableKind.LOCALS, VariableKind.PARAMETERS):
            raise ValueError("invalid variable kind")
        functions = self._context_functions(context)
        if len(functions) != 1:
            return ()
        function = functions[0]
        if not function.locations or context.pc < min(x.address for x in function.locations):
            return ()
        visible = []
        for item in self._images(function.id.module.image):
            for variable in item.variables:
                if variable.function != function.id:
                    continue
                if kind == VariableKind.LOCALS and variable.is_parameter:
                    continue
                if kind == VariableKind.PARAMETERS and not variable.is_parameter:
                    continue
                ranges = [s.extent for s in function.scopes if s.block == variable.block]
                in_block = bool(ranges and min(r.start for r in ranges) <= context.pc
                                < max(r.end_exclusive for r in ranges))
                if variable.is_parameter or in_block:
                    visible.append(variable)
        return tuple(visible)

    def lookup_type(
        self, name: str, image: Optional[ImageId] = None
    ) -> Resolution[TypeDef]:
        from ._types import PRIMITIVES, TYPE_ALIASES
        requested = TYPE_ALIASES.get(name, name)
        if requested in {t.name for t in PRIMITIVES}:
            return self._result([t for t in PRIMITIVES if t.name == requested], image)
        candidates = [t for item in self._images(image) for t in item.types
                      if t.name == requested and t.category != "incomplete"]
        return self._result(candidates, image)

    def type_by_id(self, id: TypeId) -> TypeDef:
        from ._types import PRIMITIVES
        matches = [t for item in self.images for t in item.types if t.id == id]
        matches += [t for t in PRIMITIVES if t.id == id]
        if len(matches) != 1:
            raise KeyError(id)
        return matches[0]

    def completion_catalog(self) -> CompletionCatalog:
        from ._types import PRIMITIVES, TYPE_ALIASES
        symbols = {s.name for item in self.images for s in item.symbols}
        symbols.update(f.name for item in self.images for f in item.functions)
        symbols.update(v.name for item in self.images for v in item.variables)
        symbols.update(s.name for item in self.images for module in item.modules
                       for s in module.labels)
        symbols.update(s.name[1:] for item in self.images for s in item.symbols if s.name.startswith("_"))
        symbols.update(f"{item.id.value}::{s.name}" for item in self.images for s in item.symbols)
        symbols.update(f"{item.id.value}::{f.name}" for item in self.images for f in item.functions)
        types = {t.name for item in self.images for t in item.types if t.category != "incomplete"}
        types.update(t.name for t in PRIMITIVES)
        types.update(TYPE_ALIASES)
        types.update(f"{item.id.value}::{t.name}" for item in self.images for t in item.types
                     if t.category != "incomplete")
        files = {x.source.normalized_path for x in self._locations() if x.source is not None}
        files.update(f"{x.image.value}::{x.source.normalized_path}" for x in self._locations() if x.source)
        return CompletionCatalog(tuple(sorted(symbols)), tuple(sorted(types)), tuple(sorted(files)))


def _address(value):
    if not 0 <= value <= 0xFFFF:
        raise ValueError("address must be in the 16-bit CPU space")


def _path_parts(path):
    return PurePosixPath(path.replace("\\", "/")).parts


__all__ = [
    "CompletionCatalog",
    "LineMatch",
    "Project",
    "SymbolContext",
    "SymbolMatch",
    "VariableKind",
]
