"""Typed openMSX target adapter."""

from __future__ import annotations

import re
from typing import Tuple

from .api import (
    ExecutionStatus, Instruction, PageState, RegisterSet, RemoteBreakpoint, RemoteWatchpoint,
    TargetCapabilities, TargetCommandError, TargetError, TargetProtocolError,
)
from .transport import OpenMSXTransport


_REGISTERS = (
    ("AF", "AF"), ("BC", "BC"), ("DE", "DE"), ("HL", "HL"),
    ("IX", "IX"), ("IY", "IY"), ("SP", "SP"), ("PC", "PC"),
    ("AF'", "AF2"), ("BC'", "BC2"), ("DE'", "DE2"), ("HL'", "HL2"),
    ("I", "I"), ("R", "R"), ("IM", "IM"), ("IFF", "IFF"),
)
_WORD_REGISTERS = frozenset(name for name, _ in _REGISTERS[:12])
_HEX_BYTE = re.compile(r"[0-9A-Fa-f]{2}")


class OpenMSXTarget:
    """Translate the typed Target contract to allowlisted openMSX Tcl."""

    def __init__(self, transport: OpenMSXTransport,
                 capabilities: TargetCapabilities) -> None:
        self._transport = transport
        self._capabilities = capabilities
        self._closed = False

    @property
    def capabilities(self) -> TargetCapabilities:
        return self._capabilities

    def execution_status(self) -> ExecutionStatus:
        text = self._request("execution_status", "debug breaked").strip().lower()
        if text in ("1", "true", "on"):
            return ExecutionStatus.STOPPED
        if text in ("0", "false", "off"):
            return ExecutionStatus.RUNNING
        raise self._invalid("execution_status", f"invalid break status: {text!r}")

    def read_registers(self) -> RegisterSet:
        command = "list " + " ".join(f"[reg {remote}]" for _, remote in _REGISTERS)
        fields = self._request("read_registers", command).split()
        if len(fields) != len(_REGISTERS):
            raise self._invalid(
                "read_registers",
                f"expected {len(_REGISTERS)} registers, got {len(fields)}",
            )
        values = {}
        for (name, _), field in zip(_REGISTERS, fields):
            value = self._integer(field, "read_registers")
            maximum = 0xFFFF if name in _WORD_REGISTERS else 0xFF
            if not 0 <= value <= maximum:
                raise self._invalid(
                    "read_registers", f"register {name} is outside its width"
                )
            values[name] = value
        return RegisterSet(values)

    def read_memory(self, address: int, size: int) -> bytes:
        _memory_range(address, size)
        if size == 0:
            return b""
        if self._capabilities.block_read:
            command = (
                "binary encode hex "
                f"[debug read_block memory {address} {size}]"
            )
        else:
            command = (
                "set result {}; "
                f"for {{set i 0}} {{$i < {size}}} {{incr i}} {{"
                "append result [format %02X "
                f"[debug read memory [expr {{{address} + $i}}]]]"
                "}; set result"
            )
        encoded = self._request("read_memory", command).strip()
        if len(encoded) != size * 2 or not re.fullmatch(r"[0-9A-Fa-f]*", encoded):
            raise self._invalid("read_memory", "openMSX returned truncated memory")
        return bytes.fromhex(encoded)

    def write_memory(self, address: int, data: bytes) -> None:
        data = bytes(data)
        _memory_range(address, len(data))
        if self._capabilities.memory_write is False:
            raise TargetCommandError("memory writes are unsupported", "write_memory")
        if not data:
            return
        commands = "; ".join(
            f"debug write memory {address + offset} {value}"
            for offset, value in enumerate(data)
        )
        self._request("write_memory", commands, mutation=True)

    def write_register(self, name: str, value: int) -> None:
        if self._capabilities.register_write is False:
            raise TargetCommandError("register writes are unsupported", "write_register")
        key = name.upper()
        key = {"AF2": "AF'", "BC2": "BC'", "DE2": "DE'", "HL2": "HL'"}.get(key, key)
        aliases = dict(_REGISTERS)
        halves = {
            "A": ("AF", True), "F": ("AF", False),
            "B": ("BC", True), "C": ("BC", False),
            "D": ("DE", True), "E": ("DE", False),
            "H": ("HL", True), "L": ("HL", False),
            "IXH": ("IX", True), "IXL": ("IX", False),
            "IYH": ("IY", True), "IYL": ("IY", False),
            "PCH": ("PC", True), "PCL": ("PC", False),
            "SPH": ("SP", True), "SPL": ("SP", False),
            "A2": ("AF'", True), "F2": ("AF'", False),
            "B2": ("BC'", True), "C2": ("BC'", False),
            "D2": ("DE'", True), "E2": ("DE'", False),
            "H2": ("HL'", True), "L2": ("HL'", False),
        }
        if key not in aliases and key not in halves:
            raise ValueError(f"unknown or non-writable register: {name}")
        width = 8 if key in halves or key not in _WORD_REGISTERS else 16
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < (1 << width):
            raise ValueError("register value is outside its width")
        if key in halves:
            pair, high = halves[key]
            current = self.read_registers().get(pair)
            value = ((value << 8) | (current & 0xff)) if high else ((current & 0xff00) | value)
            key = pair
        remote = aliases[key]
        self._request("write_register", f"reg {remote} {value}", mutation=True)

    def disassemble(self, address: int, count: int) -> Tuple[Instruction, ...]:
        if not 0 <= address <= 0xFFFF or count < 1 or address + count > 0x10000:
            raise ValueError("invalid disassembly range")
        output = self._request("disassemble", f"disasm {address} {count}")
        lines = output.splitlines()
        if len(lines) != count:
            raise self._invalid(
                "disassemble", f"expected {count} instructions, got {len(lines)}"
            )
        instructions = []
        for line in lines:
            if len(line) < 28:
                raise self._invalid("disassemble", f"malformed disassembly: {line!r}")
            try:
                instruction_address = int(line[:4], 16)
            except ValueError as error:
                raise self._invalid(
                    "disassemble", f"invalid instruction address: {line[:4]!r}"
                ) from error
            text = line[6:26].rstrip()
            byte_fields = line[26:].split()
            if not text or not byte_fields or any(
                _HEX_BYTE.fullmatch(field) is None for field in byte_fields
            ):
                raise self._invalid("disassemble", f"malformed disassembly: {line!r}")
            raw = bytes(int(field, 16) for field in byte_fields)
            instructions.append(Instruction(
                instruction_address, len(raw), text, raw
            ))
        return tuple(instructions)

    def read_pages(self) -> Tuple[PageState, ...]:
        pages = []
        for page in range(4):
            slots = self._request("read_pages", f"get_selected_slot {page}").split()
            if len(slots) != 2 or slots[0] not in {"0", "1", "2", "3"} or (
                slots[1] not in {"0", "1", "2", "3", "X"}
            ):
                raise self._invalid("read_pages", f"invalid slot response: {slots!r}")
            primary, secondary = slots
            mapper_secondary = "0" if secondary == "X" else secondary
            size_text = self._request(
                "read_pages", f"get_mapper_size {primary} {mapper_secondary}"
            ).strip()
            mapper_size = self._integer(size_text, "read_pages")
            if mapper_size < 0:
                raise self._invalid("read_pages", "negative mapper size")
            segment = "unknown"
            if mapper_size:
                segment = self._read_mapper_segment(page, mapper_size)
            pages.append(PageState(page, primary, secondary, segment))
        return tuple(pages)

    def continue_execution(self) -> None:
        self._command("continue_execution", "debug cont")

    def step_into(self) -> None:
        self._command("step_into", "step_in")

    def step_over(self) -> None:
        self._command("step_over", "step_over")

    def step_out(self) -> None:
        self._command("step_out", "step_out")

    def run_to(self, address: int) -> None:
        _address(address)
        self._command("run_to", f"run_to {address}")

    def interrupt(self) -> None:
        self._command("interrupt", "debug break")

    def create_breakpoint(self, address: int, condition: str = "") -> str:
        _address(address)
        if condition and self._capabilities.conditional_breakpoints is False:
            raise TargetCommandError("conditional breakpoints are unsupported",
                                     "create_breakpoint")
        suffix = "" if not condition else " -condition " + _tcl_expression(condition)
        remote_id = self._request(
            "create_breakpoint",
            f"debug breakpoint create -address {address}{suffix}",
            mutation=True,
        ).strip()
        if not remote_id or any(character.isspace() for character in remote_id):
            raise self._invalid("create_breakpoint", "invalid breakpoint id")
        return remote_id

    def remove_breakpoint(self, remote_id: str) -> None:
        if not remote_id:
            raise ValueError("breakpoint id must not be empty")
        self._command(
            "remove_breakpoint", "debug breakpoint remove " + _tcl_word(remote_id)
        )

    def list_breakpoints(self) -> Tuple[RemoteBreakpoint, ...]:
        command = (
            "set result {}; dict for {id properties} [debug breakpoint list] {"
            "append result $id { } [dict get $properties -address] \"\\n\""
            "}; set result"
        )
        text = self._request("list_breakpoints", command)
        breakpoints = []
        for line in text.splitlines():
            fields = line.split()
            if len(fields) != 2:
                raise self._invalid("list_breakpoints", "malformed breakpoint list")
            remote_id, encoded_address = fields
            address = self._integer(encoded_address, "list_breakpoints")
            try:
                breakpoints.append(RemoteBreakpoint(remote_id, address))
            except ValueError as error:
                raise self._invalid("list_breakpoints", str(error)) from error
        return tuple(breakpoints)

    def create_watchpoint(self, access: str, start: int, end: int,
                          condition: str = "") -> str:
        if self._capabilities.watchpoints is False:
            raise TargetCommandError("memory watchpoints are unsupported",
                                     "create_watchpoint")
        if access not in ("read", "write"):
            raise ValueError("watchpoint access must be read or write")
        _memory_range(start, end - start + 1)
        address = str(start) if start == end else f"{{{start} {end}}}"
        suffix = "" if not condition else " -condition " + _tcl_expression(condition)
        result = self._request("create_watchpoint",
            f"debug watchpoint create -type {access}_mem -address {address}{suffix}",
            mutation=True).strip()
        if not result or any(character.isspace() for character in result):
            raise self._invalid("create_watchpoint", "invalid watchpoint id")
        return result

    def remove_watchpoint(self, remote_id: str) -> None:
        if not remote_id: raise ValueError("watchpoint id must not be empty")
        self._command("remove_watchpoint",
                      "debug watchpoint remove " + _tcl_word(remote_id))

    def list_watchpoints(self) -> Tuple[RemoteWatchpoint, ...]:
        command = ("set result {}; dict for {id properties} [debug watchpoint list] {"
                   "append result $id { } [dict get $properties -type] { } "
                   "[dict get $properties -address] \\n}; set result")
        text = self._request("list_watchpoints", command)
        result = []
        for line in text.splitlines():
            fields = line.split()
            if len(fields) not in (3, 4):
                raise self._invalid("list_watchpoints", "malformed watchpoint list")
            remote_id, type_, *addresses = fields
            if type_ not in ("read_mem", "write_mem"):
                continue
            values = [self._integer(item, "list_watchpoints") for item in addresses]
            start, end = (values[0], values[0]) if len(values) == 1 else values
            result.append(RemoteWatchpoint(remote_id, type_.split("_", 1)[0], start, end))
        return tuple(result)

    def reset(self) -> None:
        self._command("reset", "reset")

    def save_state(self, name: str) -> None:
        self._command("save_state", "savestate " + _tcl_word(name))

    def load_state(self, name: str) -> None:
        self._command("load_state", "loadstate " + _tcl_word(name))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._transport.close()

    def _read_mapper_segment(self, page: int, mapper_size: int) -> str:
        try:
            text = self._request("read_pages", f"debug read MapperIO {page}")
        except TargetCommandError:
            text = self._request(
                "read_pages", f"debug read {{Main RAM regs}} {page}"
            )
        try:
            value = self._integer(text.strip(), "read_pages")
        except TargetProtocolError:
            return "unknown"
        return str(value & (mapper_size - 1))

    def _command(self, operation: str, tcl: str) -> None:
        self._request(operation, tcl, mutation=True)

    def _request(self, operation: str, tcl: str, mutation: bool = False) -> str:
        if self._closed:
            raise TargetError("target is closed", operation)
        try:
            reply = self._transport.request(tcl)
        except TargetError as error:
            raise type(error)(
                str(error), operation,
                outcome_unknown=error.outcome_unknown if mutation else False,
            ) from error
        if reply.status == "nok":
            raise TargetCommandError(
                reply.text or f"openMSX rejected {operation}", operation
            )
        if reply.status != "ok":
            raise self._invalid(operation, f"invalid reply status: {reply.status!r}")
        return reply.text

    @staticmethod
    def _integer(text: str, operation: str) -> int:
        try:
            return int(text, 0)
        except (TypeError, ValueError) as error:
            raise OpenMSXTarget._invalid(
                operation, f"expected integer, got {text!r}"
            ) from error

    @staticmethod
    def _invalid(operation: str, message: str) -> TargetProtocolError:
        return TargetProtocolError(message, operation)


def _address(address: int) -> None:
    if not isinstance(address, int) or not 0 <= address <= 0xFFFF:
        raise ValueError("invalid address")


def _memory_range(address: int, size: int) -> None:
    if (not isinstance(address, int) or not isinstance(size, int)
            or size < 0 or address < 0 or address + size > 0x10000):
        raise ValueError("invalid memory range")


def _tcl_word(value: str) -> str:
    """Quote one Tcl word without allowing command or variable substitution."""
    escaped = (value.replace("\\", "\\\\")
                    .replace("\"", "\\\"")
                    .replace("$", "\\$")
                    .replace("[", "\\[")
                    .replace("]", "\\]")
                    .replace("\n", "\\n")
                    .replace("\r", "\\r")
                    .replace("\t", "\\t"))
    return f'"{escaped}"'


def _tcl_expression(value: str) -> str:
    if not value or any(character in value for character in "{};\n\r"):
        raise ValueError("invalid generated Tcl expression")
    return "{" + value + "}"


__all__ = ["OpenMSXTarget"]
