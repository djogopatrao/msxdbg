"""Structural tests for the typed target boundary."""

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from msxdbg.target.api import (
    Instruction,
    RegisterSet,
    TargetCommandError,
    TargetUnavailable,
)
from msxdbg.target.fake import FakeTarget, ScriptedEvent
from msxdbg.target.transport import (
    ConnectionMode,
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


class TargetImplementationTests(unittest.TestCase):
    def test_fake_is_functional(self) -> None:
        fake = FakeTarget(
            bytes(0x10000), RegisterSet({"PC": 0}), [ScriptedEvent("status")]
        )

        self.assertEqual("stopped", fake.execution_status().value)
        self.assertEqual("bp_id_0001", fake.create_breakpoint(0x1234))


class SocketDiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_candidate(self, directory: str, name: str, mtime_ns: int) -> Path:
        parent = self.root / directory
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / name
        path.touch()
        os.utime(path, ns=(mtime_ns, mtime_ns))
        return path

    def test_explicit_socket_is_returned(self) -> None:
        expected = self.make_candidate("custom", "control.sock", 1)

        with patch("msxdbg.target.transport._is_socket", return_value=True):
            self.assertEqual(expected, discover_socket(expected))

    def test_explicit_missing_or_regular_file_is_rejected(self) -> None:
        regular = self.root / "not-a-socket"
        regular.write_text("stale")

        for path in (self.root / "missing", regular):
            with self.subTest(path=path):
                with self.assertRaises(TargetUnavailable) as raised:
                    discover_socket(path)
                self.assertEqual("discover_socket", raised.exception.operation)
                self.assertIn("attach-only", str(raised.exception))

    def test_automatic_discovery_selects_newest_socket(self) -> None:
        older = self.make_candidate("openmsx-a", "socket.1", 10)
        newest = self.make_candidate("openmsx-b", "socket.2", 20)
        (self.root / "openmsx-c").mkdir()
        (self.root / "openmsx-c" / "socket.3").write_text("not a socket")

        with patch("msxdbg.target.transport._OPENMSX_RUNTIME_ROOT", self.root), \
             patch("msxdbg.target.transport._is_socket",
                   side_effect=lambda path: path in {older, newest}):
            self.assertEqual(newest, discover_socket(None))

        self.assertNotEqual(older, newest)

    def test_mtime_tie_uses_path_as_deterministic_tiebreaker(self) -> None:
        first = self.make_candidate("openmsx-a", "socket.1", 10)
        second = self.make_candidate("openmsx-b", "socket.1", 10)

        with patch("msxdbg.target.transport._OPENMSX_RUNTIME_ROOT", self.root), \
             patch("msxdbg.target.transport._is_socket", return_value=True):
            self.assertEqual(max(first, second, key=str), discover_socket(None))

    def test_automatic_discovery_reports_attach_only_absence(self) -> None:
        with patch("msxdbg.target.transport._OPENMSX_RUNTIME_ROOT", self.root):
            with self.assertRaises(TargetUnavailable) as raised:
                discover_socket(None)

        self.assertEqual("discover_socket", raised.exception.operation)
        self.assertFalse(raised.exception.outcome_unknown)
        self.assertIn("attach-only", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
