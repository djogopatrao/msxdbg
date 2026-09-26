"""Structural tests for the typed target boundary."""

from pathlib import Path
import unittest

from msxdbg.target.api import (
    Instruction,
    RegisterSet,
    TargetCommandError,
    TargetCapabilities,
)
from msxdbg.target.fake import FakeTarget, ScriptedEvent
from msxdbg.target.openmsx import OpenMSXTarget
from msxdbg.target.transport import (
    ConnectionMode,
    OpenMSXTransport,
    TransportConfig,
    discover_socket,
)


class TargetDtoTests(unittest.TestCase):
    def test_register_input_is_copied(self) -> None:
        source = {"PC": 0x1234}
        registers = RegisterSet(source)
        source["PC"] = 0

        self.assertEqual(0x1234, registers.values["PC"])
        with self.assertRaises(TypeError):
            registers.values["PC"] = 0  # type: ignore[index]

    def test_instruction_and_transport_config_validate_boundaries(self) -> None:
        instruction = Instruction(0xFFFF, 1, "ret", b"\xc9")
        config = TransportConfig(Path("socket"), 1.0, ConnectionMode.PER_COMMAND)

        self.assertEqual(0xFFFF, instruction.address)
        self.assertEqual(ConnectionMode.PER_COMMAND, config.connection_mode)
        with self.assertRaises(ValueError):
            Instruction(0, 2, "nop", b"\x00")
        with self.assertRaises(ValueError):
            TransportConfig(Path("socket"), 0)

    def test_target_error_preserves_operation_and_outcome(self) -> None:
        error = TargetCommandError("timeout", "create_breakpoint", True)

        self.assertEqual("create_breakpoint", error.operation)
        self.assertTrue(error.outcome_unknown)


class TargetStubTests(unittest.TestCase):
    def test_transport_and_socket_discovery_fail_explicitly(self) -> None:
        transport = OpenMSXTransport(TransportConfig(Path("socket"), 1.0))

        with self.assertRaises(NotImplementedError):
            transport.request("debug read register PC")
        with self.assertRaises(NotImplementedError):
            discover_socket(None)

    def test_concrete_target_stubs_expose_typed_operations(self) -> None:
        transport = OpenMSXTransport(TransportConfig(Path("socket"), 1.0))
        openmsx = OpenMSXTarget(transport, TargetCapabilities())
        fake = FakeTarget(
            bytes(0x10000), RegisterSet({"PC": 0}), [ScriptedEvent("status")]
        )

        for target in (openmsx, fake):
            with self.subTest(target=type(target).__name__):
                with self.assertRaises(NotImplementedError):
                    target.execution_status()
                with self.assertRaises(NotImplementedError):
                    target.create_breakpoint(0x1234)


if __name__ == "__main__":
    unittest.main()
