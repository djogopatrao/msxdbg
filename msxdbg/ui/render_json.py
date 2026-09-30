"""Stable JSON envelopes for command results."""
from __future__ import annotations
import json
from msxdbg.eval.values import AddressValue, ArrayValue, ScalarValue, StringValue, StructValue, ValueResult, VariableRow
from msxdbg.session.memory_map import Page3Report
from .results import (BreakpointPayload, BreakpointTable, CommandResult,
    DisassemblyPayload, FrameTable, HelpPayload, MessagePayload, PageTable,
    RegisterTable, SourcePayload, StopPayload, SymbolPayload, UiAction)

def _decoded(value):
    if value is None: return None
    if isinstance(value, AddressValue):
        return {"kind":"address","address":value.address,
                "referenced_type":None if value.referenced_type is None else value.referenced_type.record_identity}
    if isinstance(value, ScalarValue):
        return {"kind":"scalar","value":value.value,"type":value.type_id.record_identity,"raw_bytes":value.raw_bytes.hex()}
    if isinstance(value, StringValue):
        return {"kind":"string","text":value.text,"nul_terminated":value.nul_terminated,
                "truncated":value.truncated,"raw_bytes":value.raw_bytes.hex()}
    if isinstance(value, ArrayValue):
        return {"kind":"array","items":[_decoded(item) for item in value.items],"truncated":value.truncated}
    if isinstance(value, StructValue):
        return {"kind":"struct","fields":[{"name":name,"value":_decoded(item)} for name,item in value.fields]}
    raise TypeError(f"unsupported decoded value: {type(value).__name__}")

def _location(location):
    if location is None: return None
    if location.address is not None: return {"kind":"memory","address":location.address}
    if location.register_bytes is not None: return {"kind":"registers","bytes":location.register_bytes.hex()}
    return {"kind":"unavailable","reason":location.unavailable_reason}

def _value_result(result):
    return {"kind":result.kind,"display_base":result.display_base,
            "value":_decoded(result.value),"location":_location(result.location),
            "unavailable_reason":result.unavailable_reason,"warnings":list(result.warnings)}

def _frame(frame, selected):
    function = frame.function.unique_or_none()
    return {"index":frame.index,"selected":selected,"pc":frame.pc,
            "scope_pc":frame.scope_pc,"ix":frame.ix,"state":frame.state.value,
            "function_status":frame.function.status,
            "function":function.name if function is not None else None}

def _code_location(resolution):
    location = resolution.unique_or_none()
    if location is None:
        return {"status":resolution.status,"candidates":len(resolution.candidates)}
    source = location.source
    return {"status":"unique","image":location.image.value,
            "module":location.module.key if location.module else None,
            "address":location.address,"area":location.area,"offset":location.offset,
            "source":None if source is None else {"path":source.path,
                "line":source.line,"text":source.text}}

def _breakpoint(record):
    if record is None: return None
    return {"number":record.number,"address":record.address,
            "status":record.status,"remote_id":record.remote_id,
            "condition":record.condition,
            "point_kind":record.kind,"access":record.access,"size":record.size,
            "remote_ids":list(record.remote_ids),
            "qualifier":None if record.qualifier is None else {
                "page":record.qualifier.page,"primary_slot":record.qualifier.primary_slot,
                "secondary_slot":record.qualifier.secondary_slot,
                "segment":record.qualifier.segment},
            "location":None if record.location is None else {
                "image":record.location.image.value,
                "module":record.location.module.key if record.location.module else None,
                "address":record.location.address}}

def _payload(payload):
    if isinstance(payload, ValueResult): return _value_result(payload)
    if isinstance(payload, tuple) and all(isinstance(row,VariableRow) for row in payload):
        return [{"name":row.variable.name,"location":_location(row.location),
                 "result":_value_result(row.result)} for row in payload]
    if isinstance(payload,FrameTable):
        return {"frames":[_frame(frame,frame.index == payload.selected_index)
                           for frame in payload.frames],
                "selected_index":payload.selected_index,
                "termination_reason":payload.termination_reason}
    if isinstance(payload, StopPayload):
        snapshot=payload.result.snapshot
        return {"stop_id":snapshot.stop_id,"pc":snapshot.registers.get("PC"),
                "signature_status":snapshot.signature_status,
                "reason":payload.result.reason or snapshot.known_reason,
                "matching_breakpoints":list(payload.result.matching_breakpoints),
                "location":_code_location(snapshot.pc_resolution)}
    if isinstance(payload, BreakpointPayload):
        return {"operation":payload.operation,"breakpoint":_breakpoint(payload.record)}
    if isinstance(payload, BreakpointTable):
        return {"breakpoints":[_breakpoint(item) for item in payload.records]}
    if isinstance(payload, RegisterTable):
        return {"registers":[{"name":name,"value":value,
                "width":payload.registers.width(name)}
                for name,value in sorted(payload.registers.values.items())]}
    if isinstance(payload, PageTable):
        return {"pages":[{"page":item.page,"primary_slot":item.primary_slot,
                "secondary_slot":item.secondary_slot,"segment":item.segment}
                for item in payload.pages]}
    if isinstance(payload, Page3Report):
        return {"regions":[{"name":item.name,"start":item.start,"end":item.end,
                            "unavailable_reason":item.unavailable_reason}
                           for item in payload.regions],
                "free_size":payload.free_size,"warnings":list(payload.warnings)}
    if isinstance(payload, SymbolPayload):
        return {"status":payload.resolution.status,"candidates":[{
            "name":item.symbol.name,"address":item.symbol.address,
            "offset":item.offset,"image":item.symbol.module.image.value
                if item.symbol.module else None,
            "module":item.symbol.module.key if item.symbol.module else None}
            for item in payload.resolution.candidates]}
    if isinstance(payload, SourcePayload):
        window=payload.window
        return {"path":str(window.path),"focal_line":window.focal_line,
                "lines":[{"line":number,"text":text}
                         for number,text in window.lines]}
    if isinstance(payload, DisassemblyPayload):
        result=payload.result
        return {"pc":result.pc,"next_cursor":result.next_cursor,
                "instructions":[{"address":item.address,"size":item.size,
                    "text":item.text,"raw_bytes":item.raw_bytes.hex(),
                    "location":_code_location(annotation)}
                    for item,annotation in zip(result.instructions,result.annotations)]}
    if isinstance(payload, MessagePayload): return {"message":payload.message}
    if isinstance(payload, HelpPayload):
        return {"commands":[{"name":name,"syntax":syntax,"help":help_text}
                for name,syntax,help_text in payload.entries]}
    if isinstance(payload, UiAction): return {"action":payload.action}
    raise TypeError(f"unsupported command payload: {type(payload).__name__}")

class JsonRenderer:
    def encode(self, result: CommandResult, command_index: int) -> str:
        envelope={"schema_version":1,"command_index":command_index,
                  "command":result.command,"ok":result.ok,
                  "data":None,"warnings":[],"error":None}
        if result.ok:
            envelope["data"]=_payload(result.payload)
            envelope["warnings"]=[{"code":item.code,"severity":item.severity,"message":item.message} for item in result.warnings]
        else:
            envelope["error"]={"code":result.error.code,"message":result.error.message,"details":dict(result.error.details)}
        return json.dumps(envelope,ensure_ascii=False,separators=(",",":"),allow_nan=False)

__all__=["JsonRenderer"]
