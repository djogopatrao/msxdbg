"""Contract tests for the typed openMSX target adapter."""

import unittest

from msxdbg.target.api import (
    ExecutionStatus, TargetCapabilities, TargetCommandError, TargetProtocolError,
    TargetTimeout,
)
from msxdbg.target.openmsx import OpenMSXTarget
from msxdbg.target.transport import TclReply


class ScriptedTransport:
    def __init__(self, script=()):
        self.script = list(script)
        self.requests = []
        self.close_count = 0

    def request(self, command):
        self.requests.append(command)
        if not self.script:
            raise AssertionError(f"unexpected command: {command}")
        expected, result = self.script.pop(0)
        if expected is not None:
            if callable(expected):
                assert expected(command), command
            else:
                assert expected == command, (expected, command)
        if isinstance(result, BaseException):
            raise result
        return result

    def close(self):
        self.close_count += 1


def ok(text=""):
    return TclReply("ok", text)


def target(*script):
    transport = ScriptedTransport(script)
    return OpenMSXTarget(transport, TargetCapabilities()), transport


class OpenMSXTargetTests(unittest.TestCase):
    def test_execution_status_is_strict(self):
        debugger, transport = target(
            ("debug breaked", ok("1")),
            ("debug breaked", ok("0")),
            ("debug breaked", ok("perhaps")),
        )

        self.assertEqual(ExecutionStatus.STOPPED, debugger.execution_status())
        self.assertEqual(ExecutionStatus.RUNNING, debugger.execution_status())
        with self.assertRaises(TargetProtocolError):
            debugger.execution_status()
        self.assertEqual(3, len(transport.requests))

    def test_reads_all_registers_in_one_request(self):
        values = " ".join(str(value) for value in (
            0x1234, 2, 3, 4, 5, 6, 7, 8,
            0xABCD, 10, 11, 12, 13, 14, 2, 3,
        ))
        debugger, transport = target((lambda command: command.startswith("list "), ok(values)))

        registers = debugger.read_registers()

        self.assertEqual(0x1234, registers.get("AF"))
        self.assertEqual(0xABCD, registers.get("AF'"))
        self.assertEqual(3, registers.get("IFF"))
        self.assertIn("[reg AF2]", transport.requests[0])

    def test_register_response_requires_all_values_and_valid_widths(self):
        cases = ("1 2", " ".join(["0"] * 15 + ["256"]))
        for response in cases:
            with self.subTest(response=response):
                debugger, _ = target((None, ok(response)))
                with self.assertRaises(TargetProtocolError):
                    debugger.read_registers()

    def test_memory_is_aggregated_and_validated(self):
        debugger, transport = target((lambda command: "for {set i 0}" in command,
                                      ok("00FF7A")))

        self.assertEqual(b"\x00\xff\x7a", debugger.read_memory(0x8000, 3))
        self.assertIn("32768 + $i", transport.requests[0])
        self.assertEqual(b"", debugger.read_memory(0, 0))
        self.assertEqual(1, len(transport.requests))
        for address, size in ((-1, 1), (0, -1), (0xFFFF, 2)):
            with self.subTest(address=address, size=size):
                with self.assertRaises(ValueError):
                    debugger.read_memory(address, size)

    def test_truncated_memory_is_protocol_error(self):
        debugger, _ = target((None, ok("00")))
        with self.assertRaises(TargetProtocolError):
            debugger.read_memory(0, 2)

    def test_memory_supports_last_byte_and_full_cpu_space(self):
        debugger, transport = target(
            (None, ok("FF")),
            (None, ok("00" * 0x10000)),
        )

        self.assertEqual(b"\xff", debugger.read_memory(0xFFFF, 1))
        self.assertEqual(bytes(0x10000), debugger.read_memory(0, 0x10000))
        self.assertIn("65535 + $i", transport.requests[0])
        self.assertIn("$i < 65536", transport.requests[1])

    def test_block_read_capability_uses_single_binary_safe_command(self):
        transport = ScriptedTransport((
            ("binary encode hex [debug read_block memory 32768 4]",
             ok("00ff7a80")),
        ))
        debugger = OpenMSXTarget(
            transport, TargetCapabilities(block_read=True)
        )

        self.assertEqual(b"\x00\xff\x7a\x80",
                         debugger.read_memory(0x8000, 4))
        self.assertEqual(1, len(transport.requests))

    def test_disassembly_uses_fixed_columns(self):
        lines = "\n".join((
            f"1000  {'ld a,#1':<20}3E 01",
            f"1002  {'jp 0x1234':<20}C3 34 12",
        ))
        debugger, _ = target(("disasm 4096 2", ok(lines)))

        instructions = debugger.disassemble(0x1000, 2)

        self.assertEqual((0x1000, "ld a,#1", b"\x3e\x01"),
                         (instructions[0].address, instructions[0].text,
                          instructions[0].raw_bytes))
        self.assertEqual(3, instructions[1].size)

    def test_malformed_disassembly_and_invalid_range_are_rejected(self):
        debugger, transport = target((None, ok("short")))
        with self.assertRaises(TargetProtocolError):
            debugger.disassemble(0, 1)
        for address, count in ((-1, 1), (0, 0), (0xFFFF, 2)):
            with self.subTest(address=address, count=count):
                with self.assertRaises(ValueError):
                    debugger.disassemble(address, count)
        self.assertEqual(1, len(transport.requests))

    def test_pages_read_slots_mapper_and_fallback(self):
        script = []
        for page in range(4):
            secondary = "X" if page == 0 else "2"
            script.extend((
                (f"get_selected_slot {page}", ok(f"3 {secondary}")),
                (f"get_mapper_size 3 {0 if secondary == 'X' else 2}",
                 ok("8" if page < 2 else "0")),
            ))
            if page == 0:
                script.append(("debug read MapperIO 0", ok("11")))
            elif page == 1:
                script.extend((
                    ("debug read MapperIO 1", TclReply("nok", "missing")),
                    ("debug read {Main RAM regs} 1", ok("6")),
                ))
        debugger, _ = target(*script)

        pages = debugger.read_pages()

        self.assertEqual(("3", "X", "3"),
                         (pages[0].primary_slot, pages[0].secondary_slot,
                          pages[0].segment))
        self.assertEqual("6", pages[1].segment)
        self.assertEqual("unknown", pages[2].segment)

    def test_execution_operations_emit_once(self):
        commands = (
            ("continue_execution", "debug cont"),
            ("step_into", "step_in"),
            ("step_over", "step_over"),
            ("step_out", "step_out"),
            ("run_to", "run_to 65535"),
            ("interrupt", "debug break"),
            ("reset", "reset"),
        )
        debugger, transport = target(*((command, ok()) for _, command in commands))
        debugger.continue_execution()
        debugger.step_into()
        debugger.step_over()
        debugger.step_out()
        debugger.run_to(0xFFFF)
        debugger.interrupt()
        debugger.reset()
        self.assertEqual([command for _, command in commands], transport.requests)
        with self.assertRaises(ValueError):
            debugger.run_to(0x10000)

    def test_breakpoints_preserve_remote_ids_and_external_entries(self):
        debugger, transport = target(
            ("debug breakpoint create -address 4660", ok("bp#9")),
            (lambda command: command.startswith("set result {}; dict for"),
             ok("bp#9 4660\nbp#external 0x1234\n")),
            ('debug breakpoint remove "bp#9"', ok()),
        )

        self.assertEqual("bp#9", debugger.create_breakpoint(0x1234))
        listed = debugger.list_breakpoints()
        self.assertEqual(("bp#9", "bp#external"), tuple(item.id for item in listed))
        self.assertIn('"\\n"', transport.requests[1])
        self.assertNotIn("format", transport.requests[1])
        debugger.remove_breakpoint("bp#9")
        self.assertEqual(3, len(transport.requests))

    def test_memory_and_register_writes_use_only_allowlisted_commands(self):
        debugger, transport = target(
            ("debug write memory 32768 52; debug write memory 32769 18", ok()),
            ("reg PC 4660", ok()),
        )
        debugger.write_memory(0x8000, b"\x34\x12")
        debugger.write_register("PC", 0x1234)
        self.assertEqual(2, len(transport.requests))

    def test_register_half_is_read_then_written_as_a_coherent_pair(self):
        values = " ".join(str(value) for value in (
            0, 0, 0, 0, 0, 0, 0xF000, 0x1234,
            0, 0, 0, 0, 0, 0, 0, 0,
        ))
        debugger, transport = target(
            (lambda command: command.startswith("list "), ok(values)),
            ("reg PC 4779", ok()),
        )
        debugger.write_register("PCL", 0xAB)
        self.assertEqual(2, len(transport.requests))

    def test_nok_and_malformed_breakpoint_data_do_not_succeed(self):
        debugger, _ = target((None, TclReply("nok", "rejected")))
        with self.assertRaises(TargetCommandError):
            debugger.create_breakpoint(1)
        debugger, _ = target((None, ok("bad row with extras")))
        with self.assertRaises(TargetProtocolError):
            debugger.list_breakpoints()

    def test_text_arguments_are_tcl_quoted(self):
        dangerous = 'a b; [debug cont] $x "quoted" \\ path'
        debugger, transport = target((None, ok()), (None, ok()), (None, ok()))

        debugger.save_state(dangerous)
        debugger.load_state(dangerous)
        debugger.remove_breakpoint(dangerous)

        for command in transport.requests:
            self.assertIn(r'\[debug cont\]', command)
            self.assertIn(r'\$x', command)
            self.assertIn(r'\"quoted\"', command)

    def test_transport_errors_are_relabelled_and_mutation_certainty_preserved(self):
        timeout = TargetTimeout("late", "transport.request", outcome_unknown=True)
        debugger, _ = target((None, timeout), (None, timeout))

        with self.assertRaises(TargetTimeout) as read_error:
            debugger.execution_status()
        self.assertEqual("execution_status", read_error.exception.operation)
        self.assertFalse(read_error.exception.outcome_unknown)
        with self.assertRaises(TargetTimeout) as mutation_error:
            debugger.continue_execution()
        self.assertEqual("continue_execution", mutation_error.exception.operation)
        self.assertTrue(mutation_error.exception.outcome_unknown)

    def test_close_is_idempotent_and_performs_no_cpu_command(self):
        debugger, transport = target()
        debugger.close()
        debugger.close()
        self.assertEqual(1, transport.close_count)
        self.assertEqual([], transport.requests)
        with self.assertRaises(Exception):
            debugger.execution_status()


if __name__ == "__main__":
    unittest.main()
