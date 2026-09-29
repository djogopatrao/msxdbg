"""Read-only inspection contexts are tied to one stop generation."""

import pytest

from msxdbg.debuginfo.index import Project
from msxdbg.session.core import Session
from msxdbg.session.execution import ExecutionKind, ExecutionRequest
from msxdbg.session.results import InvalidSessionState, StaleInspectionError
from msxdbg.session.state import SessionConfig
from msxdbg.target.api import RegisterSet, TargetTimeout
from msxdbg.target.fake import FakeTarget


class Clock:
    def monotonic(self): return 0.0
    def sleep(self, seconds): pass


class NeverCancelled:
    def is_cancelled(self): return False


def make_session():
    memory = bytes(range(256)) * 256
    target = FakeTarget(memory, RegisterSet({"PC": 0x100, "IX": 0x9000}))
    session = Session(Project(()), target, SessionConfig(), object(), Clock())
    return session, target


def test_inspection_requires_stopped_session():
    session, _ = make_session()
    with pytest.raises(InvalidSessionState):
        session.inspection()


def test_context_exposes_fixed_snapshot_and_symbol_scope():
    session, _ = make_session()
    session.attach()
    context = session.inspection()
    assert context.stop_id == session.where().snapshot.stop_id
    assert context.registers.get("PC") == 0x100
    assert context.frame.pc == 0x100
    assert context.symbol_context.pc == 0x100
    assert context.symbol_context.image is None


def test_memory_cache_reuses_overlap_and_returns_correct_bytes():
    session, target = make_session()
    session.attach()
    context = session.inspection()
    assert context.read_memory(0x100, 4) == bytes((0, 1, 2, 3))
    assert context.read_memory(0x102, 4) == bytes((2, 3, 4, 5))
    reads = [call for call in target.calls if call.operation == "read_memory"]
    assert [call.arguments for call in reads] == [(0x100, 4), (0x104, 2)]


def test_context_becomes_stale_on_execution_and_new_stop_reloads_memory():
    session, target = make_session()
    session.attach()
    old = session.inspection()
    old_stop_id = old.stop_id
    old.read_memory(0x200, 2)
    session.execute(ExecutionRequest(ExecutionKind.STEPI), NeverCancelled())
    with pytest.raises(StaleInspectionError):
        old.validate()
    new = session.inspection()
    assert new.stop_id != old_stop_id
    new.read_memory(0x200, 2)
    reads = [call for call in target.calls if call.operation == "read_memory"]
    assert len(reads) == 2


def test_failed_read_does_not_poison_cache():
    session, target = make_session()
    session.attach()
    context = session.inspection()
    target.inject_failure("read_memory", TargetTimeout("offline", "read_memory"))
    with pytest.raises(TargetTimeout):
        context.read_memory(0x300, 2)
    assert context.read_memory(0x300, 2) == bytes((0, 1))
    reads = [call for call in target.calls if call.operation == "read_memory"]
    assert len(reads) == 2
