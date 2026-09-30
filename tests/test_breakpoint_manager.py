"""Tests for session-owned breakpoint bookkeeping."""

import unittest

from msxdbg.debuginfo.model import CodeLocation, ImageId, Resolution, ResolutionStatus
from msxdbg.session.breakpoints import BreakpointManager, BreakpointStatus
from msxdbg.session.results import ResolvedTarget
from msxdbg.target.api import RemoteBreakpoint, TargetTimeout


class FakeBreakpointTarget:
    def __init__(self):
        self.next_id = 1
        self.remote = {}
        self.create_calls = []
        self.remove_calls = []
        self.create_error = None
        self.remove_errors = {}

    def create_breakpoint(self, address):
        self.create_calls.append(address)
        if self.create_error:
            raise self.create_error
        rid = f"remote-{self.next_id}"
        self.next_id += 1
        self.remote[rid] = address
        return rid

    def remove_breakpoint(self, rid):
        self.remove_calls.append(rid)
        if rid in self.remove_errors:
            raise self.remove_errors[rid]
        self.remote.pop(rid, None)

    def list_breakpoints(self):
        return tuple(RemoteBreakpoint(rid, address) for rid, address in self.remote.items())


def resolved(address):
    location = CodeLocation(ImageId("resident"), address)
    return ResolvedTarget(address, Resolution(ResolutionStatus.UNIQUE, (location,)),
                          f"address {address:#x}")


class BreakpointManagerTests(unittest.TestCase):
    def setUp(self):
        self.target = FakeBreakpointTarget()
        self.manager = BreakpointManager(self.target)

    def test_create_uses_target_id_and_preserves_location(self):
        record = self.manager.create(resolved(0x100))
        self.assertEqual([0x100], self.target.create_calls)
        self.assertEqual("remote-1", record.remote_id)
        self.assertEqual(0x100, record.location.address)

    def test_number_not_reused_after_confirmed_failure(self):
        self.target.create_error = TargetTimeout("rejected", "create", False)
        with self.assertRaises(TargetTimeout):
            self.manager.create(resolved(0x100))
        self.target.create_error = None
        self.assertEqual(2, self.manager.create(resolved(0x200)).number)

    def test_uncertain_creation_retained_without_invented_id(self):
        self.target.create_error = TargetTimeout("uncertain", "create", True)
        with self.assertRaises(TargetTimeout):
            self.manager.create(resolved(0x100))
        record = self.manager.records()[0]
        self.assertEqual(BreakpointStatus.UNKNOWN, record.status)
        self.assertIsNone(record.remote_id)

    def test_delete_preserves_record_on_remote_failure(self):
        record = self.manager.create(resolved(0x200))
        self.target.remove_errors[record.remote_id] = TargetTimeout("failed", "remove")
        with self.assertRaises(TargetTimeout):
            self.manager.delete(record.number)
        self.assertEqual((record,), self.manager.records())

    def test_unknown_number_does_not_touch_target(self):
        with self.assertRaises(ValueError):
            self.manager.delete(99)
        self.assertEqual([], self.target.remove_calls)

    def test_suspend_removes_remote_and_is_idempotent(self):
        record = self.manager.create(resolved(0x300))
        suspended = self.manager.suspend(record.number)
        self.assertEqual(["remote-1"], self.target.remove_calls)
        self.assertEqual(BreakpointStatus.SUSPENDED, suspended.status)
        self.assertIsNone(suspended.remote_id)
        self.manager.suspend(record.number)
        self.assertEqual(["remote-1"], self.target.remove_calls)

    def test_uncertain_suspend_is_not_confirmed(self):
        record = self.manager.create(resolved(0x300))
        self.target.remove_errors[record.remote_id] = TargetTimeout("uncertain", "remove", True)
        with self.assertRaises(TargetTimeout):
            self.manager.suspend(record.number)
        self.assertEqual(BreakpointStatus.UNKNOWN, self.manager.records()[0].status)

    def test_resume_recreates_remote_with_same_number(self):
        record = self.manager.create(resolved(0x400))
        self.manager.suspend(record.number)
        resumed = self.manager.resume(record.number)
        self.assertEqual(record.number, resumed.number)
        self.assertEqual("remote-2", resumed.remote_id)
        self.assertEqual([0x400, 0x400], self.target.create_calls)

    def test_matching_excludes_suspended(self):
        active = self.manager.create(resolved(0x500))
        suspended = self.manager.create(resolved(0x500))
        self.manager.suspend(suspended.number)
        self.assertEqual((active.number,), self.manager.matching(0x500))

    def test_reconcile_uses_identity_not_address(self):
        present = self.manager.create(resolved(0x600))
        absent = self.manager.create(resolved(0x700))
        del self.target.remote[absent.remote_id]
        self.target.remote["external"] = 0x700
        records = self.manager.reconcile()
        self.assertEqual(present.remote_id, records[0].remote_id)
        self.assertEqual(BreakpointStatus.SUSPENDED, records[1].status)
        self.assertIsNone(records[1].remote_id)

    def test_cleanup_continues_and_reports_all_outcomes(self):
        failed = self.manager.create(resolved(0x800))
        removed = self.manager.create(resolved(0x900))
        self.target.remove_errors[failed.remote_id] = TargetTimeout("offline", "remove")
        self.target.create_error = TargetTimeout("uncertain", "create", True)
        with self.assertRaises(TargetTimeout):
            self.manager.create(resolved(0xA00))
        report = self.manager.cleanup()
        self.assertEqual((removed.remote_id,), report.removed_ids)
        self.assertEqual((failed.remote_id,), report.pending_ids)
        self.assertEqual((3,), report.unknown_creations)
        self.assertEqual(1, len(report.errors))


if __name__ == "__main__":
    unittest.main()
