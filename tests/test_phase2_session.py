"""End-to-end Phase 2 tests using the offline target."""

from msxdbg.debuginfo.index import Project
from msxdbg.session.core import Session
from msxdbg.session.execution import ExecutionKind, ExecutionRequest
from msxdbg.session.results import TargetQuery
from msxdbg.session.state import SessionConfig, SessionState
from msxdbg.target.api import RegisterSet, TargetTimeout
from msxdbg.target.fake import FakeTarget


class Clock:
    def __init__(self): self.now = 0.0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds


class NeverCancelled:
    def is_cancelled(self): return False


def session_at(pc=0x100):
    target = FakeTarget(bytes(0x10000), RegisterSet({"PC": pc}))
    return Session(Project(()), target, SessionConfig(), object(), Clock()), target


def test_lifecycle_step_until_and_stop_snapshots():
    session, _ = session_at()
    assert session.attach() == SessionState.STOPPED
    first = session.where().snapshot
    stepped = session.execute(ExecutionRequest(ExecutionKind.STEPI), NeverCancelled())
    assert stepped.snapshot.registers.get("PC") == 0x101
    assert stepped.snapshot.stop_id > first.stop_id
    stopped = session.execute(ExecutionRequest(ExecutionKind.UNTIL, address=0x2345), NeverCancelled())
    assert stopped.snapshot.registers.get("PC") == 0x2345


def test_resolve_breakpoint_suspend_resume_and_close_cleanup():
    session, target = session_at()
    session.attach()
    resolved = session.resolve_target(TargetQuery(address=0x3456)).candidates[0]
    created = session.add_breakpoint(resolved)
    assert created.remote_id == "bp_id_0001"
    assert session.suspend_breakpoint(created.number).remote_id is None
    resumed = session.resume_breakpoint(created.number)
    assert resumed.number == created.number
    assert resumed.remote_id == "bp_id_0002"
    report = session.close()
    assert report.removed_ids == ("bp_id_0002",)
    assert target.calls[-1].operation == "close"
    assert session.state == SessionState.CLOSED


def test_fake_target_failure_is_one_shot_and_can_happen_after_apply():
    _, target = session_at()
    target.inject_failure("create_breakpoint", TargetTimeout("uncertain", "create_breakpoint", True), True)
    try:
        target.create_breakpoint(0x4000)
    except TargetTimeout:
        pass
    else:
        raise AssertionError("injected failure was not raised")
    assert target.list_breakpoints()[0].address == 0x4000
    assert target.create_breakpoint(0x5000) == "bp_id_0002"
