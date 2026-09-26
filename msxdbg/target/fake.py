"""Deterministic typed target stub for future session tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

from .api import RegisterSet, TargetError, _UnimplementedTarget


@dataclass(frozen=True)
class ScriptedEvent:
    operation: str
    arguments: Tuple[object, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", tuple(self.arguments))


@dataclass(frozen=True)
class TargetCall:
    operation: str
    arguments: Tuple[object, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "arguments", tuple(self.arguments))


class FakeTarget(_UnimplementedTarget):
    def __init__(
        self,
        memory: bytes,
        registers: RegisterSet,
        script: Sequence[ScriptedEvent] = (),
    ) -> None:
        if len(memory) != 0x10000:
            raise ValueError("FakeTarget memory must contain exactly 64 KiB")
        self._memory = bytes(memory)
        self._registers = registers
        self._script = tuple(script)

    def inject_failure(
        self,
        operation: str,
        error: TargetError,
        after_apply: bool = False,
    ) -> None:
        raise NotImplementedError("FakeTarget.inject_failure is not implemented")

    @property
    def calls(self) -> Tuple[TargetCall, ...]:
        raise NotImplementedError("FakeTarget.calls is not implemented")


__all__ = ["FakeTarget", "ScriptedEvent", "TargetCall"]
