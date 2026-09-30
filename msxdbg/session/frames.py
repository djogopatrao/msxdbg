"""Stack-frame analysis contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, Tuple

from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import (AbsoluteStorage, Function, RegisterStorage,
                                   Resolution, StackStorage, UnknownStorage, Variable)
from msxdbg.target.api import Instruction, RegisterSet
from .results import LocationResult
from .state import StopSnapshot


class FrameState(str, Enum):
    IX_ACTIVE = "ix-active"
    FRAMELESS = "frameless"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Frame:
    index: int
    pc: int
    scope_pc: int
    function: Resolution[Function]
    ix: Optional[int]
    state: FrameState


@dataclass(frozen=True)
class BacktraceResult:
    frames: Tuple[Frame, ...]
    termination_reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "frames", tuple(self.frames))


class FrameReader(Protocol):
    def read_memory(self, address: int, size: int) -> bytes: ...
    def disassemble(self, address: int, count: int) -> Tuple[Instruction, ...]: ...


class FrameService:
    _SDCC_IX_PROLOGUE = (b"\xdd\xe5", b"\xdd\x21\x00\x00", b"\xdd\x39")
    _POP_IX = b"\xdd\xe1"

    def __init__(self, project: Optional[Project] = None, frame_limit: int = 64) -> None:
        if frame_limit < 1:
            raise ValueError("frame limit must be positive")
        self._project = project
        self._frame_limit = frame_limit

    def walk(self, snapshot: StopSnapshot, reader: FrameReader) -> BacktraceResult:
        pc = snapshot.registers.get("PC")
        function = self._function_at(pc, reader)
        current = function.unique_or_none()
        try:
            ix = snapshot.registers.get("IX")
        except KeyError:
            ix = None
        state = (self.frame_state(current, pc, reader)
                 if current is not None else FrameState.UNKNOWN)
        frames = [Frame(0, pc, pc, function, ix, state)]

        if current is None:
            return BacktraceResult(tuple(frames), "unknown-current-function")
        if state != FrameState.IX_ACTIVE or ix is None:
            return BacktraceResult(tuple(frames), "current-frame-not-active")

        seen_ix = {ix}
        while len(frames) < self._frame_limit:
            if ix > 0xFFFC:
                return BacktraceResult(tuple(frames), "invalid-frame-address")
            raw = reader.read_memory(ix, 4)
            if len(raw) != 4:
                return BacktraceResult(tuple(frames), "invalid-frame-data")
            caller_ix = int.from_bytes(raw[:2], "little")
            return_address = int.from_bytes(raw[2:], "little")
            if return_address == 0:
                return BacktraceResult(tuple(frames), "invalid-return-address")
            if caller_ix in seen_ix:
                return BacktraceResult(tuple(frames), "frame-pointer-cycle")

            scope_pc = return_address - 1
            caller_function = self._function_at(scope_pc, reader)
            caller = caller_function.unique_or_none()
            caller_state = (self.frame_state(caller, scope_pc, reader)
                            if caller is not None else FrameState.UNKNOWN)
            frames.append(Frame(
                len(frames), return_address, scope_pc, caller_function,
                caller_ix if caller_ix != 0 else None, caller_state,
            ))
            if caller is None:
                return BacktraceResult(tuple(frames), "unknown-caller")
            if caller_state == FrameState.FRAMELESS:
                return BacktraceResult(tuple(frames), "caller-without-ix-frame")
            if caller_state != FrameState.IX_ACTIVE or caller_ix == 0:
                return BacktraceResult(tuple(frames), "caller-frame-state-unknown")
            seen_ix.add(caller_ix)
            ix = caller_ix

        return BacktraceResult(tuple(frames), "frame-limit")

    def _function_at(self, address: int, reader: FrameReader) -> Resolution[Function]:
        if self._project is not None:
            return self._project.function_at(address)
        resolver = getattr(reader, "function_at", None)
        if resolver is None:
            raise ValueError("frame walking requires project function resolution")
        return resolver(address)

    def frame_state(self, function: Function, pc: int, reader: FrameReader) -> FrameState:
        if not 0 <= pc <= 0xFFFF:
            raise ValueError("frame PC must be a CPU address")
        if pc < function.entry or (function.end is not None and pc >= function.end):
            return FrameState.UNKNOWN

        prologue = reader.disassemble(function.entry, len(self._SDCC_IX_PROLOGUE))
        if not prologue:
            return FrameState.UNKNOWN
        if prologue[0].address != function.entry:
            return FrameState.UNKNOWN
        if prologue[0].raw_bytes != self._SDCC_IX_PROLOGUE[0]:
            return FrameState.FRAMELESS
        if len(prologue) < len(self._SDCC_IX_PROLOGUE):
            return FrameState.UNKNOWN

        expected_address = function.entry
        for instruction, expected_bytes in zip(prologue, self._SDCC_IX_PROLOGUE):
            if instruction.address != expected_address or instruction.raw_bytes != expected_bytes:
                return FrameState.UNKNOWN
            expected_address += instruction.size

        if pc < expected_address:
            return FrameState.UNKNOWN

        span = pc - function.entry + 1
        instructions = reader.disassemble(function.entry, span)
        for instruction in instructions:
            if instruction.address >= pc:
                break
            if instruction.address >= expected_address and instruction.raw_bytes == self._POP_IX:
                # Static address order cannot prove that a branch executed this epilogue.
                return FrameState.UNKNOWN
        return FrameState.IX_ACTIVE

    def locate(self, variable: Variable, frame: Frame, registers: RegisterSet, reader: FrameReader) -> LocationResult:
        storage = variable.storage
        if isinstance(storage, AbsoluteStorage):
            return LocationResult(address=storage.address)
        if isinstance(storage, UnknownStorage):
            return LocationResult(unavailable_reason=storage.reason)
        if isinstance(storage, RegisterStorage):
            if frame.index != 0:
                return LocationResult(
                    unavailable_reason="register storage is unavailable in caller frames"
                )
            data = bytearray()
            try:
                for name in storage.registers:
                    width = registers.width(name)
                    data.extend(registers.get(name).to_bytes(width // 8, "little"))
            except KeyError as error:
                return LocationResult(unavailable_reason=f"register {error.args[0]} is unavailable")
            return LocationResult(register_bytes=bytes(data))
        if isinstance(storage, StackStorage):
            if frame.state != FrameState.IX_ACTIVE or frame.ix is None:
                return LocationResult(unavailable_reason="stack variable requires a proven IX frame")
            address = frame.ix + storage.offset
            if not 0 <= address <= 0xFFFF:
                return LocationResult(unavailable_reason="stack variable address is outside CPU memory")
            return LocationResult(address=address)
        return LocationResult(unavailable_reason="unsupported variable storage")


__all__ = ["BacktraceResult", "Frame", "FrameReader", "FrameService", "FrameState"]
