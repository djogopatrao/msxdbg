"""Plain presentation of command results."""
from __future__ import annotations
from typing import Protocol
from msxdbg.eval.values import AddressValue, ArrayValue, ScalarValue, StringValue, StructValue, ValueResult, VariableRow
from msxdbg.session.memory_map import Page3Report
from .results import (BreakpointPayload, BreakpointTable, CommandResult,
    DisassemblyPayload, FrameTable, HelpPayload, MessagePayload, PageTable,
    RegisterTable, SourcePayload, StopPayload, SymbolPayload, UiAction)

class Console(Protocol):
    def print(self, *objects: object) -> None: ...

def _escape(text): return str(text).replace("[", "\\[")

def _scalar(value, base):
    if not isinstance(value, int) or isinstance(value, bool): return str(value)
    if base == 16: return ("-0x" + format(-value, "x")) if value < 0 else hex(value)
    if base == 2: return ("-0b" + format(-value, "b")) if value < 0 else bin(value)
    return str(value)

def _value(value, base=10):
    if value is None: return "<unavailable>"
    if isinstance(value, AddressValue): return f"0x{value.address:04x}"
    if isinstance(value, ScalarValue): return _scalar(value.value, base)
    if isinstance(value, StringValue):
        suffix = "…" if value.truncated else ""
        return repr(value.text + suffix)
    if isinstance(value, ArrayValue):
        suffix = ", …" if value.truncated else ""
        return "[" + ", ".join(_value(item) for item in value.items) + suffix + "]"
    if isinstance(value, StructValue):
        return "{" + ", ".join(f"{_escape(name)}={_value(item)}" for name,item in value.fields) + "}"
    raise TypeError(f"unsupported decoded value: {type(value).__name__}")

def _result(result):
    if result.unavailable_reason is not None: return f"<unavailable: {_escape(result.unavailable_reason)}>"
    text = _value(result.value, result.display_base)
    if result.kind == "memory" and result.location and result.location.address is not None:
        text = f"0x{result.location.address:04x}: {text}"
    return text

def _qualifier(value):
    if value is None: return ""
    parts=[]
    if value.page is not None: parts.append(f"page {value.page}")
    if value.primary_slot is not None:
        slot=str(value.primary_slot)
        if value.secondary_slot is not None: slot+=f".{value.secondary_slot}"
        parts.append("slot " + slot)
    if value.segment is not None: parts.append(f"segment {value.segment}")
    return ("  " + " ".join(parts)) if parts else ""

def _frame(frame, selected):
    marker = "*" if selected else " "
    function = frame.function.unique_or_none()
    name = function.name if function is not None else "??"
    text = f"{marker}#{frame.index}  0x{frame.pc:04x} in {name} ()"
    if function is not None:
        locations = [item for item in function.locations
                     if item.address <= frame.scope_pc and item.source is not None]
        if locations:
            source = max(locations, key=lambda item: item.address).source
            text += f" at {_escape(source.path)}:{source.line}"
    return text

class TextRenderer:
    def render(self, result: CommandResult, console: Console) -> None:
        if not result.ok:
            console.print(f"error[{_escape(result.error.code)}]: {_escape(result.error.message)}")
            return
        payload = result.payload
        if isinstance(payload, ValueResult):
            console.print(_result(payload)); return
        if isinstance(payload, tuple) and all(isinstance(row, VariableRow) for row in payload):
            if not payload: console.print("<no variables>")
            for row in payload: console.print(f"{_escape(row.variable.name)} = {_result(row.result)}")
            return
        if isinstance(payload, FrameTable):
            for frame in payload.frames:
                console.print(_frame(frame, frame.index == payload.selected_index))
            if payload.termination_reason is not None:
                console.print(f"<backtrace stopped: {_escape(payload.termination_reason)}>")
            return
        if isinstance(payload, StopPayload):
            snapshot=payload.result.snapshot; pc=snapshot.registers.get("PC")
            location=snapshot.pc_resolution.unique_or_none()
            suffix=""
            if location is not None:
                suffix=f" {location.image.value}::{location.module.key if location.module else '?'}"
                if location.source is not None:
                    suffix+=f" {_escape(location.source.path)}:{location.source.line}"
            console.print(f"stopped at 0x{pc:04x}{suffix}"); return
        if isinstance(payload, BreakpointPayload):
            if payload.record is None: console.print("breakpoint deleted")
            else:
                condition = f" if {_escape(payload.record.condition)}" if payload.record.condition else ""
                qualifier = _qualifier(payload.record.qualifier)
                label = (f"Watchpoint {payload.record.number} {payload.record.access} "
                         f"0x{payload.record.address:04x}+{payload.record.size}"
                         if payload.record.kind == "watchpoint" else
                         f"Breakpoint {payload.record.number} at 0x{payload.record.address:04x}")
                console.print(f"{label}{condition}{qualifier} ({payload.record.status})")
            return
        if isinstance(payload, BreakpointTable):
            if not payload.records: console.print("No breakpoints.")
            for item in payload.records:
                condition = f"  if {_escape(item.condition)}" if item.condition else ""
                qualifier = _qualifier(item.qualifier)
                kind = (f"watch {item.access} +{item.size}" if item.kind == "watchpoint" else "break")
                source = ""
                if item.location is not None and item.location.source is not None:
                    span = item.location.source
                    source = f"  {_escape(span.path)}:{span.line}"
                console.print(f"{item.number}  {kind}  0x{item.address:04x}{source}  {item.status}{condition}{qualifier}")
            return
        if isinstance(payload, RegisterTable):
            for name,value in sorted(payload.registers.values.items()):
                width=payload.registers.width(name); digits=4 if width == 16 else 2
                console.print(f"{name}  0x{value:0{digits}x}  {value}")
            return
        if isinstance(payload, PageTable):
            for item in payload.pages:
                console.print(f"page {item.page}: slot {item.primary_slot}.{item.secondary_slot} segment {item.segment}")
            return
        if isinstance(payload, Page3Report):
            for region in payload.regions:
                if region.start is None or region.end is None:
                    console.print(f"{region.name}: <unknown: {_escape(region.unavailable_reason or 'limit unavailable')}>")
                else:
                    console.print(f"{region.name}: 0x{region.start:04x}..0x{region.end:04x} ({region.end-region.start} bytes)")
            console.print("free: " + (str(payload.free_size) if payload.free_size is not None else "<unknown>"))
            for warning in payload.warnings: console.print("warning: " + _escape(warning))
            return
        if isinstance(payload, SymbolPayload):
            if not payload.resolution.candidates: console.print("<symbol unavailable>")
            for item in payload.resolution.candidates:
                console.print(f"0x{item.symbol.address:04x} is {_escape(item.symbol.name)}+0x{item.offset:x}")
            return
        if isinstance(payload, SourcePayload):
            for number,text in payload.window.lines:
                marker=">" if number == payload.window.focal_line else " "
                console.print(f"{marker} {number:5d}  {_escape(text)}")
            return
        if isinstance(payload, DisassemblyPayload):
            for item in payload.result.instructions:
                marker="=>" if item.address == payload.result.pc else "  "
                console.print(f"{marker} 0x{item.address:04x}  {_escape(item.text)}")
            return
        if isinstance(payload, MessagePayload): console.print(_escape(payload.message)); return
        if isinstance(payload, HelpPayload):
            for name,syntax,help_text in payload.entries:
                console.print(f"{_escape(syntax):32} {_escape(help_text)}")
            return
        if isinstance(payload, UiAction): return
        raise TypeError(f"unsupported command payload: {type(payload).__name__}")

__all__=["Console","TextRenderer"]
