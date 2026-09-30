import pytest

from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import Resolution, ResolutionStatus
from msxdbg.session.core import Session
from msxdbg.session.results import InvalidSessionState, StopResult
from msxdbg.session.state import (SessionConfig, SessionState, SignatureSpec,
                                  StopSnapshot)
from msxdbg.target.api import RegisterSet
from msxdbg.target.fake import FakeTarget


class Clock:
    def monotonic(self): return 0.0
    def sleep(self, seconds): pass


class NeverCancelled:
    def is_cancelled(self): return False


class Cancelled:
    def is_cancelled(self): return True


def snapshot(status, stop_id=1):
    return StopSnapshot(stop_id, stop_id, RegisterSet({"PC": 0x100}),
        Resolution(ResolutionStatus.MISSING), status)


class Stops:
    def __init__(self, session, statuses):
        self.session = session
        self.statuses = iter(statuses)
        self.requests = []
    def run(self, request, hooks, cancel):
        self.requests.append(request)
        result = StopResult(snapshot(next(self.statuses), len(self.requests)))
        self.session._snapshot = result.snapshot
        self.session._state = SessionState.STOPPED
        return result


def make_session(signature=True, limit=3):
    target = FakeTarget(bytes(0x10000), RegisterSet({"PC": 0x100}))
    config = SessionConfig(SignatureSpec(0x200, b"MSX") if signature else None,
                           execution_timeout=2.0,
                           signature_attempt_limit=limit)
    session = Session(Project(()), target, config, object(), Clock())
    session._state = SessionState.STOPPED
    session._snapshot = snapshot("pending")
    return session


def test_until_signature_rejects_missing_configuration_before_execution():
    session = make_session(signature=False)
    with pytest.raises(InvalidSessionState, match="configured signature"):
        session.continue_until_signature(1.0, NeverCancelled())


def test_until_signature_requires_finite_positive_timeout():
    session = make_session()
    for value in (None, 0, -1):
        with pytest.raises(ValueError, match="finite positive timeout"):
            session.continue_until_signature(value, NeverCancelled())


def test_until_signature_returns_current_verified_stop_without_resuming():
    session = make_session()
    session._snapshot = snapshot("verified")
    controller = Stops(session, [])
    session._execution_controller = controller
    result = session.continue_until_signature(1.0, NeverCancelled())
    assert result.snapshot.signature_status == "verified"
    assert controller.requests == []


def test_until_signature_resumes_across_pending_stops_until_verified():
    session = make_session()
    controller = Stops(session, ["pending", "pending", "verified"])
    session._execution_controller = controller
    result = session.continue_until_signature(1.5, NeverCancelled())
    assert result.snapshot.signature_status == "verified"
    assert len(controller.requests) == 3
    assert all(item.timeout_seconds == 1.5 for item in controller.requests)


def test_until_signature_cancel_does_not_resume_from_confirmed_stop():
    session = make_session()
    controller = Stops(session, [])
    session._execution_controller = controller
    result = session.continue_until_signature(1.0, Cancelled())
    assert result.reason == "cancelled"
    assert controller.requests == []


def test_until_signature_limit_leaves_confirmed_stopped_target():
    session = make_session(limit=2)
    controller = Stops(session, ["pending", "pending"])
    session._execution_controller = controller
    with pytest.raises(TimeoutError, match="after 2 stops; target is stopped"):
        session.continue_until_signature(1.0, NeverCancelled())
    assert session.state == SessionState.STOPPED
