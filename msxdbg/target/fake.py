"""Deterministic in-memory Target implementation for offline tests."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple
from .api import ExecutionStatus, Instruction, PageState, RegisterSet, RemoteBreakpoint, RemoteWatchpoint, TargetCapabilities, TargetError

@dataclass(frozen=True)
class ScriptedEvent:
    operation: str
    arguments: Tuple[object, ...] = ()
    def __post_init__(self): object.__setattr__(self, "arguments", tuple(self.arguments))

@dataclass(frozen=True)
class TargetCall:
    operation: str
    arguments: Tuple[object, ...] = ()

@dataclass(frozen=True)
class _Failure:
    error: TargetError
    after_apply: bool

class FakeTarget:
    def __init__(self, memory: bytes, registers: RegisterSet, script: Sequence[ScriptedEvent] = (), capabilities: Optional[TargetCapabilities] = None, pages: Optional[Sequence[PageState]] = None):
        if len(memory) != 0x10000: raise ValueError("FakeTarget memory must contain exactly 64 KiB")
        self._memory = bytes(memory); self._registers = RegisterSet(dict(registers.values))
        self._script = list(script); self._calls = []; self._failures: Dict[str, _Failure] = {}
        self._breakpoints: Dict[str, Tuple[int, str]] = {}; self._watchpoints = {}; self._states = {}; self._next_id = 1
        self._status = ExecutionStatus.STOPPED; self._closed = False
        self.capabilities = capabilities or TargetCapabilities()
        self._pages = tuple(pages) if pages is not None else tuple(
            PageState(i,"0","0","unknown") for i in range(4))

    def inject_failure(self, operation, error, after_apply=False): self._failures[operation] = _Failure(error, after_apply)
    @property
    def calls(self): return tuple(self._calls)
    def _begin(self, operation, *args):
        if self._closed and operation != "close": raise TargetError("target is closed", operation)
        self._calls.append(TargetCall(operation, tuple(args)))
        if self._script:
            expected = self._script.pop(0)
            aliases = {"status": "execution_status"}
            expected_operation = aliases.get(expected.operation, expected.operation)
            if expected_operation != operation or (expected.arguments and expected.arguments != tuple(args)):
                raise AssertionError(f"expected {expected}, got {operation}{tuple(args)!r}")
        failure = self._failures.pop(operation, None)
        if failure and not failure.after_apply: raise failure.error
        return failure
    @staticmethod
    def _finish(failure):
        if failure: raise failure.error
    def _set_pc(self, value):
        values = dict(self._registers.values); values["PC"] = value & 0xffff; self._registers = RegisterSet(values)
    def execution_status(self):
        f=self._begin("execution_status"); result=self._status; self._finish(f); return result
    def read_registers(self):
        f=self._begin("read_registers"); result=RegisterSet(dict(self._registers.values)); self._finish(f); return result
    def read_memory(self, address, size):
        if size < 0 or address < 0 or address + size > 0x10000: raise ValueError("invalid memory range")
        f=self._begin("read_memory", address, size); result=self._memory[address:address+size]; self._finish(f); return result
    def write_memory(self, address, data):
        data=bytes(data)
        if address < 0 or address + len(data) > 0x10000: raise ValueError("invalid memory range")
        f=self._begin("write_memory",address,data)
        memory=bytearray(self._memory); memory[address:address+len(data)]=data; self._memory=bytes(memory)
        self._finish(f)
    def write_register(self,name,value):
        key=name.upper()
        key={"AF2":"AF'","BC2":"BC'","DE2":"DE'","HL2":"HL'"}.get(key,key)
        width=self._registers.width(key)
        if not isinstance(value,int) or isinstance(value,bool) or not 0 <= value < (1 << width):
            raise ValueError("register value is outside its width")
        f=self._begin("write_register",key,value)
        values=dict(self._registers.values)
        halves={"A":"AF","F":"AF","B":"BC","C":"BC","D":"DE","E":"DE",
                "H":"HL","L":"HL","IXH":"IX","IXL":"IX","IYH":"IY","IYL":"IY",
                "PCH":"PC","PCL":"PC","SPH":"SP","SPL":"SP"}
        halves.update({"A2":"AF'","F2":"AF'","B2":"BC'","C2":"BC'",
                       "D2":"DE'","E2":"DE'","H2":"HL'","L2":"HL'"})
        if key in halves and halves[key] in values:
            pair=halves[key]; high=key.endswith("H") or key in ("A","B","D","H","A2","B2","D2","H2")
            values[pair]=((value << 8) | (values[pair] & 0xff)) if high else ((values[pair] & 0xff00) | value)
        else:
            values[key]=value
        self._registers=RegisterSet(values); self._finish(f)
    def disassemble(self, address, count):
        if not 0 <= address <= 0xffff or count < 1 or address + count > 0x10000: raise ValueError("invalid disassembly range")
        f=self._begin("disassemble", address, count)
        result=tuple(Instruction(address+i, 1, "nop", self._memory[address+i:address+i+1]) for i in range(count)); self._finish(f); return result
    def read_pages(self):
        f=self._begin("read_pages"); result=self._pages; self._finish(f); return result
    def continue_execution(self):
        f=self._begin("continue_execution"); self._status=ExecutionStatus.RUNNING; self._finish(f)
    def _step(self, operation):
        f=self._begin(operation); self._status=ExecutionStatus.RUNNING; self._set_pc(self._registers.get("PC")+1); self._status=ExecutionStatus.STOPPED; self._finish(f)
    def step_into(self): self._step("step_into")
    def step_over(self): self._step("step_over")
    def step_out(self): self._step("step_out")
    def run_to(self, address):
        if not 0 <= address <= 0xffff: raise ValueError("invalid address")
        f=self._begin("run_to",address); self._status=ExecutionStatus.RUNNING; self._set_pc(address); self._status=ExecutionStatus.STOPPED; self._finish(f)
    def interrupt(self):
        f=self._begin("interrupt"); self._status=ExecutionStatus.STOPPED; self._finish(f)
    def create_breakpoint(self, address, condition=""):
        if not 0 <= address <= 0xffff: raise ValueError("invalid address")
        f=self._begin("create_breakpoint",address,condition) if condition else self._begin("create_breakpoint",address)
        rid=f"bp_id_{self._next_id:04d}"; self._next_id+=1; self._breakpoints[rid]=(address,condition); self._finish(f); return rid
    def remove_breakpoint(self, remote_id):
        f=self._begin("remove_breakpoint",remote_id)
        if remote_id not in self._breakpoints: raise TargetError("unknown breakpoint","remove_breakpoint")
        del self._breakpoints[remote_id]; self._finish(f)
    def list_breakpoints(self):
        f=self._begin("list_breakpoints"); result=tuple(RemoteBreakpoint(k,v[0]) for k,v in self._breakpoints.items()); self._finish(f); return result
    def create_watchpoint(self, access, start, end, condition=""):
        f=self._begin("create_watchpoint",access,start,end,condition); rid=f"wp_id_{self._next_id:04d}"; self._next_id+=1
        self._watchpoints[rid]=(access,start,end,condition); self._finish(f); return rid
    def remove_watchpoint(self, remote_id):
        f=self._begin("remove_watchpoint",remote_id)
        if remote_id not in self._watchpoints: raise TargetError("unknown watchpoint","remove_watchpoint")
        del self._watchpoints[remote_id]; self._finish(f)
    def list_watchpoints(self):
        f=self._begin("list_watchpoints"); result=tuple(RemoteWatchpoint(k,v[0],v[1],v[2]) for k,v in self._watchpoints.items()); self._finish(f); return result
    def reset(self):
        f=self._begin("reset"); self._set_pc(0); self._status=ExecutionStatus.STOPPED; self._finish(f)
    def save_state(self,name):
        f=self._begin("save_state",name); self._states[name]=(self._registers,self._memory); self._finish(f)
    def load_state(self,name):
        f=self._begin("load_state",name)
        if name not in self._states: raise TargetError("unknown state","load_state")
        self._registers,self._memory=self._states[name]; self._status=ExecutionStatus.STOPPED; self._finish(f)
    def close(self):
        if self._closed: return
        f=self._begin("close"); self._closed=True; self._finish(f)

__all__=["FakeTarget","ScriptedEvent","TargetCall"]
