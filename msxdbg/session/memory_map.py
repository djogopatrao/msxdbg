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

    def __post_init__(self) -> None:
        if self.symbol is not None and self.address is not None:
            raise ValueError("memory limit must use either symbol or address")
        if self.address is not None and not 0 <= self.address <= 0xFFFF:
            raise ValueError("memory-limit address outside CPU space")


@dataclass(frozen=True)
class MemoryLayoutPolicy:
    page_start: int
    page_end: int
    heap_start: MemoryLimit
    stack_limit: MemoryLimit

    def __post_init__(self) -> None:
        if not 0 <= self.page_start < self.page_end <= 0x10000:
            raise ValueError("invalid memory page bounds")


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
        context.validate()
        heap, heap_reason = self._resolve(policy.heap_start, context, project, "heap")
        stack, stack_reason = self._resolve(policy.stack_limit, context, project, "stack")
        if (policy.stack_limit.symbol is None and policy.stack_limit.address is None
                and not policy.stack_limit.read_word):
            try:
                stack, stack_reason = context.registers.get("SP"), None
            except KeyError:
                stack, stack_reason = None, "SP register is unavailable"
        def valid(value):
            return value is not None and policy.page_start <= value <= policy.page_end
        if heap is not None and not valid(heap):
            heap_reason, heap = "heap limit lies outside page bounds", None
        if stack is not None and not valid(stack):
            stack_reason, stack = "stack limit lies outside page bounds", None
        regions = (
            MemoryRegion("data", policy.page_start, heap, heap_reason),
            MemoryRegion("heap", heap, None,
                         heap_reason or "heap extent is not separately configured"),
            MemoryRegion("free", heap, stack,
                         heap_reason or stack_reason),
            MemoryRegion("stack", stack, policy.page_end, stack_reason),
            MemoryRegion("reserved", policy.page_end, 0x10000),
        )
        warnings = []
        free_size = None
        if heap is not None and stack is not None:
            if heap < stack:
                free_size = stack - heap
            else:
                warnings.append("heap reaches or exceeds the stack; possible corruption")
        context.validate()
        return Page3Report(regions, free_size, tuple(warnings))

    @staticmethod
    def _resolve(limit: MemoryLimit, context: InspectionContext,
                 project: Project, label: str):
        address = limit.address
        if limit.symbol is not None:
            result = project.lookup_symbol(limit.symbol,
                                           context.symbol_context.image)
            symbol = result.unique_or_none()
            if symbol is None:
                return None, f"{label} symbol is unavailable or ambiguous"
            address = symbol.address
        if address is None:
            return None, f"{label} limit is not configured"
        if limit.read_word:
            data = context.read_memory(address, 2)
            return int.from_bytes(data, "little"), None
        return address, None


DEFAULT_PAGE3_POLICY = MemoryLayoutPolicy(
    0xC000, 0x10000, MemoryLimit(), MemoryLimit()
)


__all__ = ["DEFAULT_PAGE3_POLICY", "MemoryLayoutPolicy", "MemoryLimit", "MemoryMapService", "MemoryRegion", "Page3Report"]
