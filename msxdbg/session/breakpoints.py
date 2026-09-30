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
class MappingQualifier:
    page: Optional[int] = None
    primary_slot: Optional[int] = None
    secondary_slot: Optional[int] = None
    segment: Optional[int] = None

    def __post_init__(self):
        if self.page is not None and self.page not in (0,1,2,3):
            raise ValueError("page must be between 0 and 3")
        for value in (self.primary_slot,self.secondary_slot):
            if value is not None and value not in (0,1,2,3):
                raise ValueError("slot must be between 0 and 3")
        if self.secondary_slot is not None and self.primary_slot is None:
            raise ValueError("secondary slot requires a primary slot")
        if self.segment is not None and self.segment < 0:
            raise ValueError("segment must be non-negative")
        if self.segment is not None and self.page is None:
            raise ValueError("segment qualifier requires page")


@dataclass(frozen=True)
class BreakpointRecord:
    number: int
    address: int
    location: Optional[CodeLocation]
    remote_id: Optional[str]
    status: str = BreakpointStatus.ACTIVE
    condition: Optional[str] = None
    kind: str = "breakpoint"
    access: Optional[str] = None
    size: int = 1
    remote_ids: Tuple[str, ...] = ()
    qualifier: Optional[MappingQualifier] = None


@dataclass
class _BreakpointContext:
    number: int
    address: int
    location: Optional[CodeLocation]
    remote_id: Optional[str] = None
    status: str = BreakpointStatus.UNKNOWN
    condition: Optional[str] = None
    kind: str = "breakpoint"
    access: Optional[str] = None
    size: int = 1
    remote_ids: Tuple[str, ...] = ()
    remote_condition: Optional[str] = None
    qualifier: Optional[MappingQualifier] = None

    def record(self) -> BreakpointRecord:
        ids = self.remote_ids or ((self.remote_id,) if self.remote_id else ())
        return BreakpointRecord(self.number, self.address, self.location, self.remote_id,
                                self.status, self.condition, self.kind, self.access,
                                self.size, ids, self.qualifier)


class BreakpointManager:
    def __init__(self, remote: Target) -> None:
        self._remote = remote
        self._breakpoints: Dict[int, _BreakpointContext] = {}
        self._next_number = 1

    def create(self, target: ResolvedTarget, condition: Optional[str] = None,
               remote_condition: Optional[str] = None,
               qualifier: Optional[MappingQualifier] = None) -> BreakpointRecord:
        number = self._next_number
        self._next_number += 1
        context = _BreakpointContext(number, target.address, target.location.unique_or_none(),
                                     condition=condition,
                                     remote_condition=remote_condition or condition,
                                     qualifier=qualifier)
        try:
            compiled=context.remote_condition
            context.remote_id = (self._remote.create_breakpoint(target.address, compiled)
                                 if compiled else self._remote.create_breakpoint(target.address))
        except TargetError as error:
            if error.outcome_unknown:
                self._breakpoints[number] = context
            raise
        context.status = BreakpointStatus.ACTIVE
        self._breakpoints[number] = context
        return context.record()

    def create_watchpoint(self, access: str, address: int, size: int,
                          condition: Optional[str] = None) -> BreakpointRecord:
        if access not in ("read", "write", "access"):
            raise ValueError("watch access must be read, write, or access")
        if size < 1 or address < 0 or address + size > 0x10000:
            raise ValueError("watchpoint range is outside CPU memory")
        number=self._next_number; self._next_number+=1
        context=_BreakpointContext(number,address,None,status=BreakpointStatus.UNKNOWN,
            condition=condition,kind="watchpoint",access=access,size=size)
        created=[]
        try:
            for mode in (("read","write") if access == "access" else (access,)):
                created.append(self._remote.create_watchpoint(
                    mode,address,address+size-1,condition or ""))
        except TargetError as error:
            context.remote_ids=tuple(created); context.remote_id=created[0] if created else None
            if error.outcome_unknown or created: self._breakpoints[number]=context
            raise
        context.remote_ids=tuple(created); context.remote_id=created[0]
        context.status=BreakpointStatus.ACTIVE; self._breakpoints[number]=context
        return context.record()

    def _remove_remote(self, context):
        ids=context.remote_ids or ((context.remote_id,) if context.remote_id else ())
        first_error=None
        for remote_id in ids:
            try:
                if context.kind == "watchpoint": self._remote.remove_watchpoint(remote_id)
                else: self._remote.remove_breakpoint(remote_id)
            except Exception as error:
                if first_error is None: first_error=error
        if first_error is not None: raise first_error

    def delete(self, number: int) -> None:
        context = self._require(number)
        if context.remote_id is not None:
            try:
                self._remove_remote(context)
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
            self._remove_remote(context)
        except TargetError as error:
            if error.outcome_unknown:
                context.status = BreakpointStatus.UNKNOWN
            raise
        context.remote_id = None
        context.remote_ids = ()
        context.status = BreakpointStatus.SUSPENDED
        return context.record()

    def resume(self, number: int) -> BreakpointRecord:
        context = self._require(number)
        if context.status in (BreakpointStatus.ACTIVE, BreakpointStatus.UNKNOWN):
            return context.record()
        try:
            if context.kind == "watchpoint":
                modes=("read","write") if context.access == "access" else (context.access,)
                ids=tuple(self._remote.create_watchpoint(mode,context.address,
                    context.address+context.size-1,context.condition or "") for mode in modes)
                remote_id=ids[0]; context.remote_ids=ids
            else:
                remote_id = (self._remote.create_breakpoint(context.address, context.remote_condition)
                             if context.remote_condition else self._remote.create_breakpoint(context.address))
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
        breakpoint_ids = {breakpoint.id for breakpoint in self._remote.list_breakpoints()}
        watchpoint_ids = ({watchpoint.id for watchpoint in self._remote.list_watchpoints()}
                          if any(item.kind == "watchpoint" for item in self._breakpoints.values())
                          else set())
        for context in self._breakpoints.values():
            if context.remote_id is None:
                continue
            expected=set(context.remote_ids or (context.remote_id,))
            remote_ids=watchpoint_ids if context.kind == "watchpoint" else breakpoint_ids
            if expected and expected <= remote_ids:
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
                self._remove_remote(context)
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


__all__ = ["BreakpointManager", "BreakpointRecord", "BreakpointStatus", "MappingQualifier"]
