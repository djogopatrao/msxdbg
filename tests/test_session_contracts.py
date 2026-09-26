"""Structural tests for session DTOs and explicit stubs."""

import unittest

from msxdbg.debuginfo.index import Project
from msxdbg.session.breakpoints import BreakpointManager
from msxdbg.session.core import Session
from msxdbg.session.results import LocationResult, TargetQuery
from msxdbg.session.safety import DangerousAction, InteractiveEntry, SafetyGate
from msxdbg.session.state import SessionConfig, SignatureSpec
from msxdbg.target.api import RegisterSet
from msxdbg.target.fake import FakeTarget


class SessionDtoTests(unittest.TestCase):
    def test_signature_rejects_wrap_and_empty_bytes(self) -> None:
        self.assertEqual(b"MSX", SignatureSpec(0x100, b"MSX").expected)
        with self.assertRaises(ValueError):
            SignatureSpec(0, b"")
        with self.assertRaises(ValueError):
            SignatureSpec(0xFFFF, b"xx")

    def test_target_query_requires_one_complete_kind(self) -> None:
        self.assertEqual(0x1234, TargetQuery(address=0x1234).address)
        self.assertEqual(10, TargetQuery(path="main.c", line=10).line)
        with self.assertRaises(ValueError):
            TargetQuery()
        with self.assertRaises(ValueError):
            TargetQuery(path="main.c")
        with self.assertRaises(ValueError):
            TargetQuery(address=1, symbol="foo")

    def test_location_result_distinguishes_unavailable_from_zero(self) -> None:
        self.assertEqual(0, LocationResult(address=0).address)
        self.assertEqual("no frame", LocationResult(unavailable_reason="no frame").unavailable_reason)
        with self.assertRaises(ValueError):
            LocationResult()


class SessionStubTests(unittest.TestCase):
    def test_session_and_breakpoint_services_fail_explicitly(self) -> None:
        target = FakeTarget(bytes(0x10000), RegisterSet({"PC": 0}))
        project = Project([])
        session = Session(project, target, SessionConfig(), object(), object())  # type: ignore[arg-type]
        breakpoints = BreakpointManager(target)

        with self.assertRaises(NotImplementedError):
            session.attach()
        with self.assertRaises(NotImplementedError):
            breakpoints.records()

    def test_safety_gate_does_not_issue_placeholder_permits(self) -> None:
        gate = SafetyGate()
        entry = InteractiveEntry("reset yes", True)

        with self.assertRaises(NotImplementedError):
            gate.authorize_typed(DangerousAction.RESET, entry)


if __name__ == "__main__":
    unittest.main()
