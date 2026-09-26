"""Immutable project-query contracts for offline debug information."""

from __future__ import annotations

from dataclasses import dataclass
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
)


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

    def __post_init__(self) -> None:
        object.__setattr__(self, "images", tuple(self.images))

    def resolve(
        self, address: int, image: Optional[ImageId] = None
    ) -> Resolution[CodeLocation]:
        raise NotImplementedError("Project.resolve is not implemented")

    def resolve_line(
        self, path: str, line: int, image: Optional[ImageId] = None
    ) -> Resolution[LineMatch]:
        raise NotImplementedError("Project.resolve_line is not implemented")

    def lookup_symbol(
        self, name: str, image: Optional[ImageId] = None
    ) -> Resolution[Symbol]:
        raise NotImplementedError("Project.lookup_symbol is not implemented")

    def nearest_symbol(
        self, address: int, image: Optional[ImageId] = None
    ) -> Resolution[SymbolMatch]:
        raise NotImplementedError("Project.nearest_symbol is not implemented")

    def function_at(
        self, address: int, image: Optional[ImageId] = None
    ) -> Resolution[Function]:
        raise NotImplementedError("Project.function_at is not implemented")

    def find_variable(
        self, name: str, context: SymbolContext
    ) -> Resolution[Variable]:
        raise NotImplementedError("Project.find_variable is not implemented")

    def variables_in_scope(
        self, context: SymbolContext, kind: str
    ) -> Tuple[Variable, ...]:
        raise NotImplementedError("Project.variables_in_scope is not implemented")

    def lookup_type(
        self, name: str, image: Optional[ImageId] = None
    ) -> Resolution[TypeDef]:
        raise NotImplementedError("Project.lookup_type is not implemented")

    def type_by_id(self, id: TypeId) -> TypeDef:
        raise NotImplementedError("Project.type_by_id is not implemented")

    def completion_catalog(self) -> CompletionCatalog:
        raise NotImplementedError("Project.completion_catalog is not implemented")


__all__ = [
    "CompletionCatalog",
    "LineMatch",
    "Project",
    "SymbolContext",
    "SymbolMatch",
    "VariableKind",
]
