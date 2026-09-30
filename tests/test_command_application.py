"""Session lifecycle around shell and batch execution."""

from io import StringIO
import pytest

from msxdbg.session.results import CloseReport
from msxdbg.ui.application import CommandApplication


class Session:
    def __init__(self, report=CloseReport(), close_error=None):
        self.report=report; self.close_error=close_error; self.closes=0
    def close(self):
        self.closes += 1
        if self.close_error: raise self.close_error
        return self.report


class Context:
    def __init__(self, session): self.session=session


class Repl:
    def __init__(self, result=0, error=None): self.result=result; self.error=error
    def run(self, context):
        if self.error: raise self.error
        return self.result


class Batch:
    def __init__(self, result=0, error=None): self.result=result; self.error=error
    def run(self, commands, context, writer):
        if self.error: raise self.error
        writer.write("ran\n"); return self.result


def test_shell_and_exec_always_close_once():
    shell_session=Session(); errors=StringIO()
    assert CommandApplication(repl=Repl(0)).run_shell(Context(shell_session),errors)==0
    assert shell_session.closes==1
    exec_session=Session(); output=StringIO()
    assert CommandApplication(batch=Batch(1)).run_exec(("bad",),Context(exec_session),output,errors)==1
    assert output.getvalue()=="ran\n" and exec_session.closes==1


def test_original_error_is_not_masked_by_cleanup_failure():
    session=Session(close_error=RuntimeError("close failed")); errors=StringIO()
    original=ValueError("command failed")
    with pytest.raises(ValueError,match="command failed"):
        CommandApplication(repl=Repl(error=original)).run_shell(Context(session),errors)
    assert "cleanup error: RuntimeError: close failed" in errors.getvalue()
    assert session.closes==1


def test_cleanup_failure_propagates_without_original_error():
    session=Session(close_error=RuntimeError("close failed"))
    with pytest.raises(RuntimeError,match="close failed"):
        CommandApplication(repl=Repl()).run_shell(Context(session),StringIO())


def test_cleanup_report_is_written_to_error_stream():
    report=CloseReport(pending_ids=("bp-1",),unknown_creations=(3,),errors=("network",))
    session=Session(report); errors=StringIO()
    assert CommandApplication(repl=Repl()).run_shell(Context(session),errors)==1
    text=errors.getvalue()
    assert "cleanup error: network" in text
    assert "cleanup pending breakpoint: bp-1" in text
    assert "cleanup uncertain breakpoint: 3" in text
