"""Batch execution for Phase 3 commands."""

from io import StringIO
import json

from msxdbg.ui.batch import BatchPolicy, BatchRunner
from msxdbg.ui.results import CommandResult, MessagePayload
from test_phase3_handlers import command_context


def decoded_lines(writer):
    return [json.loads(line) for line in writer.getvalue().splitlines()]


def test_batch_runs_in_order_with_one_json_object_per_command():
    context, session = command_context()
    writer = StringIO()
    status = BatchRunner().run(("print 1+2", "print PC+1", "info locals"),
                               context, writer)
    lines = decoded_lines(writer)
    assert status == 0
    assert [item["command_index"] for item in lines] == [0, 1, 2]
    assert [item["command"] for item in lines] == ["print", "print", "info"]
    assert lines[0]["data"]["value"]["value"] == 3
    assert lines[1]["data"]["value"]["value"] == 0x1235
    assert session.calls == 2  # live print and locals; constant print stays offline


def test_batch_stops_after_first_error_and_does_not_run_later_command():
    context, session = command_context()
    writer = StringIO()
    status = BatchRunner().run(("print 1", "print 1/0", "print PC"), context, writer)
    lines = decoded_lines(writer)
    assert status == 1
    assert len(lines) == 2
    assert lines[0]["ok"] is True
    assert lines[1]["ok"] is False
    assert session.calls == 0


def test_batch_refuses_unregistered_dangerous_commands_before_session_access():
    context, session = command_context()
    writer = StringIO()
    status = BatchRunner().run(("reset yes", "load yes"), context, writer)
    lines = decoded_lines(writer)
    assert status == 1
    assert len(lines) == 1
    assert lines[0]["error"]["code"] == "command-not-available-in-batch"
    assert session.calls == 0


def test_empty_batch_succeeds_without_output():
    context, _ = command_context(); writer = StringIO()
    assert BatchRunner().run((), context, writer) == 0
    assert writer.getvalue() == ""


def test_batch_refuses_clear_and_has_a_finite_global_deadline():
    context, session = command_context(); writer = StringIO()
    assert BatchRunner().run(("clear",), context, writer) == 1
    assert decoded_lines(writer)[0]["error"]["code"] == "command-not-available-in-batch"
    assert session.calls == 0

    ticks = iter((0.0, 31.0))
    writer = StringIO()
    runner = BatchRunner(policy=BatchPolicy(30.0), clock=lambda: next(ticks))
    assert runner.run(("print PC",), context, writer) == 1
    assert decoded_lines(writer)[0]["error"]["code"] == "batch-timeout"
    assert session.calls == 0


def test_batch_policy_requires_a_positive_timeout():
    try:
        BatchPolicy(0)
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("zero timeout was accepted")


def test_batch_propagates_remaining_deadline_and_restores_context():
    context, _ = command_context()
    seen = []
    class Dispatcher:
        def specification(self, command): return None
        def dispatch(self, command, current):
            seen.append((current.execution_timeout, current.cancellation.is_cancelled()))
            return CommandResult("test", True, MessagePayload("ok"))
    ticks = iter((0.0, 2.0, 3.0, 4.0))
    writer = StringIO()
    runner = BatchRunner(Dispatcher(), policy=BatchPolicy(10),
                         clock=lambda: next(ticks))
    assert runner.run(("test",), context, writer) == 0
    assert seen == [(8.0, False)]
    assert context.execution_timeout is None and context.cancellation is None


def test_batch_converts_unexpected_dispatch_failure_to_json_error():
    context, _ = command_context()
    class Dispatcher:
        def specification(self, command): return None
        def dispatch(self, command, current): raise RuntimeError("boom")
    writer = StringIO()
    assert BatchRunner(Dispatcher()).run(("explode",), context, writer) == 1
    error = decoded_lines(writer)[0]["error"]
    assert error["code"] == "internal-error"
    assert error["details"]["error_type"] == "RuntimeError"
