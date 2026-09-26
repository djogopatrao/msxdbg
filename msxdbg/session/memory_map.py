"""Page-3 memory-layout reporting contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from msxdbg.debuginfo.index import Project
from .state import InspectionContext


@dataclass(frozen=True)
class MemoryLimit:
    symbol: Optional[str] = None
    address: Optional[int] = None
    read_word: bool = False


@dataclass(frozen=True)
class MemoryLayoutPolicy:
    page_start: int
    page_end: int
    heap_start: MemoryLimit
    stack_limit: MemoryLimit


@dataclass(frozen=True)
class MemoryRegion:
    name: str
    start: Optional[int]
    end: Optional[int]
    unavailable_reason: Optional[str] = None


@dataclass(frozen=True)
class Page3Report:
    regions: Tuple[MemoryRegion, ...]
    free_size: Optional[int]
    warnings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "regions", tuple(self.regions))
        object.__setattr__(self, "warnings", tuple(self.warnings))


class MemoryMapService:
    def page3(self, context: InspectionContext, project: Project, policy: MemoryLayoutPolicy) -> Page3Report:
        raise NotImplementedError("MemoryMapService.page3 is not implemented")


__all__ = ["MemoryLayoutPolicy", "MemoryLimit", "MemoryMapService", "MemoryRegion", "Page3Report"]
