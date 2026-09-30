"""Stable, read-only view of one stopped target generation."""

from __future__ import annotations

from typing import Callable, Dict

from msxdbg.debuginfo.index import SymbolContext
from msxdbg.debuginfo.model import Variable
from msxdbg.target.api import Target
from .frames import Frame, FrameService
from .results import LocationResult, StaleInspectionError
from .state import StopSnapshot


class StopInspectionContext:
    def __init__(self, snapshot: StopSnapshot, frame: Frame, target: Target,
                 memory_cache: Dict[int, int], frame_service: FrameService,
                 is_current: Callable[[int], bool]) -> None:
        self._snapshot = snapshot
        self._frame = frame
        self._target = target
        self._memory_cache = memory_cache
        self._frame_service = frame_service
        self._is_current = is_current

    @property
    def stop_id(self) -> int:
        self.validate()
        return self._snapshot.stop_id

    @property
    def frame(self) -> Frame:
        self.validate()
        return self._frame

    @property
    def registers(self):
        self.validate()
        return self._snapshot.registers

    @property
    def signature_status(self) -> str:
        self.validate()
        return self._snapshot.signature_status

    @property
    def symbol_context(self) -> SymbolContext:
        self.validate()
        location = self._frame.function.unique_or_none()
        function = location.id if location is not None else None
        module = function.module if function is not None else None
        image = module.image if module is not None else None
        return SymbolContext(image, module, function, self._frame.scope_pc)

    def read_memory(self, address: int, size: int) -> bytes:
        self.validate()
        if size < 0 or address < 0 or address + size > 0x10000:
            raise ValueError("memory range outside 16-bit address space")
        end = address + size
        cursor = address
        while cursor < end:
            if cursor in self._memory_cache:
                cursor += 1
                continue
            missing_end = cursor + 1
            while missing_end < end and missing_end not in self._memory_cache:
                missing_end += 1
            data = self._target.read_memory(cursor, missing_end - cursor)
            for offset, value in enumerate(data):
                self._memory_cache[cursor + offset] = value
            cursor = missing_end
        result = bytes(self._memory_cache[position] for position in range(address, end))
        self.validate()
        return result

    def locate_variable(self, variable: Variable) -> LocationResult:
        self.validate()
        result = self._frame_service.locate(
            variable, self._frame, self._snapshot.registers, self
        )
        self.validate()
        return result

    def validate(self) -> None:
        if not self._is_current(self._snapshot.stop_id):
            raise StaleInspectionError(
                f"inspection context for stop {self._snapshot.stop_id} is stale"
            )


__all__ = ["StopInspectionContext"]
