"""Bookkeeping for breakpoints owned by a debugging session."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from msxdbg.debuginfo.model import CodeLocation
from msxdbg.target.api import Target, TargetError
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


@dataclass
class _BreakpointContext:
    number: int
    address: int
    location: Optional[CodeLocation]
    remote_id: Optional[str] = None
    status: str = BreakpointStatus.UNKNOWN

    def record(self) -> BreakpointRecord:
        return BreakpointRecord(self.number, self.address, self.location, self.remote_id, self.status)


class BreakpointManager:
    def __init__(self, remote: Target) -> None:
        self._remote = remote
        self._breakpoints: Dict[int, _BreakpointContext] = {}
        self._next_number = 1

    def create(self, target: ResolvedTarget) -> BreakpointRecord:
        number = self._next_number
        self._next_number += 1
        context = _BreakpointContext(number, target.address, target.location.unique_or_none())
        try:
            context.remote_id = self._remote.create_breakpoint(target.address)
        except TargetError as error:
            if error.outcome_unknown:
                self._breakpoints[number] = context
            raise
        context.status = BreakpointStatus.ACTIVE
        self._breakpoints[number] = context
        return context.record()

    def delete(self, number: int) -> None:
        context = self._require(number)
        if context.remote_id is not None:
            try:
                self._remote.remove_breakpoint(context.remote_id)
            except TargetError as error:
                if error.outcome_unknown:
                    context.status = BreakpointStatus.UNKNOWN
                raise
        del self._breakpoints[number]

    def suspend(self, number: int) -> BreakpointRecord:
        context = self._require(number)
        if context.status == BreakpointStatus.SUSPENDED or context.remote_id is None:
            return context.record()
        try:
            self._remote.remove_breakpoint(context.remote_id)
        except TargetError as error:
            if error.outcome_unknown:
                context.status = BreakpointStatus.UNKNOWN
            raise
        context.remote_id = None
        context.status = BreakpointStatus.SUSPENDED
        return context.record()

    def resume(self, number: int) -> BreakpointRecord:
        context = self._require(number)
        if context.status in (BreakpointStatus.ACTIVE, BreakpointStatus.UNKNOWN):
            return context.record()
        try:
            remote_id = self._remote.create_breakpoint(context.address)
        except TargetError as error:
            if error.outcome_unknown:
                context.status = BreakpointStatus.UNKNOWN
            raise
        context.remote_id = remote_id
        context.status = BreakpointStatus.ACTIVE
        return context.record()

    def records(self) -> Tuple[BreakpointRecord, ...]:
        return tuple(self._breakpoints[n].record() for n in sorted(self._breakpoints))

    def matching(self, address: int) -> Tuple[int, ...]:
        return tuple(n for n, ctx in sorted(self._breakpoints.items())
                     if ctx.address == address and ctx.status == BreakpointStatus.ACTIVE)

    def reconcile(self) -> Tuple[BreakpointRecord, ...]:
        remote_ids = {breakpoint.id for breakpoint in self._remote.list_breakpoints()}
        for context in self._breakpoints.values():
            if context.remote_id is None:
                continue
            if context.remote_id in remote_ids:
                context.status = BreakpointStatus.ACTIVE
            else:
                context.remote_id = None
                context.status = BreakpointStatus.SUSPENDED
        return self.records()

    def cleanup(self) -> CloseReport:
        removed_ids = []
        pending_ids = []
        unknown_creations = []
        errors = []
        for number in sorted(tuple(self._breakpoints)):
            context = self._breakpoints[number]
            if context.remote_id is None:
                if context.status == BreakpointStatus.UNKNOWN:
                    unknown_creations.append(number)
                else:
                    del self._breakpoints[number]
                continue
            try:
                self._remote.remove_breakpoint(context.remote_id)
            except Exception as error:
                pending_ids.append(context.remote_id)
                errors.append(f"cleanup local #{number} remote {context.remote_id!r}: "
                              f"{type(error).__name__}: {error}")
                if isinstance(error, TargetError) and error.outcome_unknown:
                    context.status = BreakpointStatus.UNKNOWN
            else:
                removed_ids.append(context.remote_id)
                del self._breakpoints[number]
        return CloseReport(tuple(removed_ids), tuple(pending_ids),
                           tuple(unknown_creations), tuple(errors))

    def _require(self, number: int) -> _BreakpointContext:
        try:
            return self._breakpoints[number]
        except KeyError:
            raise ValueError(f"local breakpoint #{number} does not exist") from None


__all__ = ["BreakpointManager", "BreakpointRecord", "BreakpointStatus"]
