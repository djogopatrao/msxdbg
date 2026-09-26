"""Owned-breakpoint bookkeeping contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from msxdbg.debuginfo.model import CodeLocation
from msxdbg.target.api import Target
from .results import CloseReport, ResolvedTarget


class BreakpointStatus:
    ACTIVE = "active"
    SUSPENDED = "suspended"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BreakpointRecord:
    number: int
    address: int
    location: Optional[CodeLocation]
    remote_id: Optional[str]
    status: str = BreakpointStatus.ACTIVE


class BreakpointManager:
    def __init__(self, remote: Target) -> None:
        self._remote = remote

    def create(self, target: ResolvedTarget) -> BreakpointRecord:
        raise NotImplementedError("BreakpointManager.create is not implemented")
    def delete(self, number: int) -> None:
        raise NotImplementedError("BreakpointManager.delete is not implemented")
    def suspend(self, number: int) -> BreakpointRecord:
        raise NotImplementedError("BreakpointManager.suspend is not implemented")
    def resume(self, number: int) -> BreakpointRecord:
        raise NotImplementedError("BreakpointManager.resume is not implemented")
    def records(self) -> Tuple[BreakpointRecord, ...]:
        raise NotImplementedError("BreakpointManager.records is not implemented")
    def matching(self, address: int) -> Tuple[int, ...]:
        raise NotImplementedError("BreakpointManager.matching is not implemented")
    def reconcile(self) -> Tuple[BreakpointRecord, ...]:
        raise NotImplementedError("BreakpointManager.reconcile is not implemented")
    def cleanup(self) -> CloseReport:
        raise NotImplementedError("BreakpointManager.cleanup is not implemented")


__all__ = ["BreakpointManager", "BreakpointRecord", "BreakpointStatus"]
