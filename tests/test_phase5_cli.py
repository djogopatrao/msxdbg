"""Phase 5 shell/exec CLI composition without a real emulator."""

from types import SimpleNamespace

import pytest

import msxdbg.__main__ as cli
from msxdbg.session.state import SignatureSpec, StepMode
from msxdbg.target.api import TargetProtocolError
from msxdbg.target.transport import TclReply


def test_main_dispatches_normalized_shell_options(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(cli, "run_shell", lambda options: captured.append(options) or 7)
    status = cli.main(["shell", "--out", str(tmp_path), "--socket", "/tmp/openmsx.sock",
        "--source-root", str(tmp_path / "src"), "--mode", "asm",
        "--verify-signature", "0x100=C31101"])
    assert status == 7
    options = captured[0]
    assert options.outputs == (tmp_path,)
    assert options.socket.as_posix() == "/tmp/openmsx.sock"
    assert options.mode == StepMode.ASSEMBLY
    assert options.signature == SignatureSpec(0x100, bytes.fromhex("C31101"))


def test_main_dispatches_exec_commands_timeout_and_json(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(cli, "run_exec", lambda options: captured.append(options) or 0)
    assert cli.main(["exec", "--out", str(tmp_path), "-c", "where",
        "-c", "info locals", "--json", "--timeout", "12.5"]) == 0
    options = captured[0]
    assert options.commands == ("where", "info locals")
    assert options.timeout_seconds == 12.5
    assert options.mode == StepMode.SOURCE


@pytest.mark.parametrize("arguments", (
    ["exec", "--out", "out", "-c", "where", "--json", "--timeout", "0"],
    ["exec", "--out", "out", "-c", "where"],
    ["shell", "--out", "out", "--verify-signature", "0x100=ABC"],
))
def test_live_cli_rejects_invalid_usage(arguments, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments)
    assert error.value.code == 2
    assert "error" in capsys.readouterr().err


def test_run_live_attaches_then_delegates_to_application(monkeypatch):
    events = []
    class Session:
        def attach(self): events.append("attach")
        def close(self): events.append("close")
    context = SimpleNamespace(session=Session())
    loaded = SimpleNamespace(diagnostics=())
    monkeypatch.setattr(cli, "_compose_context",
        lambda options, origin: (events.append(("compose", origin)) or (loaded, context)))
    class Application:
        def __init__(self, **kwargs): events.append(("application", tuple(kwargs)))
        def run_shell(self, current, errors): events.append("shell"); return 0
        def run_exec(self, commands, current, output, errors):
            events.append(("exec", commands)); return 0
    monkeypatch.setattr(cli, "CommandApplication", Application)
    monkeypatch.setattr(cli, "BatchRunner", lambda policy: object())
    shell = cli.ShellOptions((__import__("pathlib").Path("out"),))
    assert cli.run_shell(shell) == 0
    execute = cli.ExecOptions((__import__("pathlib").Path("out"),), ("where",), 5)
    assert cli.run_exec(execute) == 0
    assert events[0:3] == [("compose", "interactive"), "attach", ("application", ())]
    assert "shell" in events and ("exec", ("where",)) in events


def test_live_initialization_failure_has_no_traceback(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_compose_context",
        lambda options, origin: (_ for _ in ()).throw(RuntimeError("offline")))
    assert cli.run_shell(cli.ShellOptions((__import__("pathlib").Path("out"),))) == 1
    error = capsys.readouterr().err
    assert "RuntimeError: offline" in error and "Traceback" not in error


def test_live_target_enables_only_probed_optimizations(monkeypatch, tmp_path):
    class Transport:
        def __init__(self, config):
            self.config = config
            self.replies = iter((ok("0"), ok("0"), ok("ff")))
            self.closed = False
        def request(self, command): return next(self.replies)
        def close(self): self.closed = True
    def ok(text): return TclReply("ok", text)
    created = []
    monkeypatch.setattr(cli, "OpenMSXTransport",
        lambda config: created.append(Transport(config)) or created[-1])

    target = cli._build_live_target(tmp_path / "socket")

    assert target.capabilities.persistent
    assert target.capabilities.block_read
    assert len(created) == 1


def test_live_target_falls_back_when_read_only_probe_fails(monkeypatch, tmp_path):
    class Transport:
        def __init__(self, config, fail):
            self.config = config; self.fail = fail; self.closed = False
        def request(self, command):
            if self.fail:
                raise TargetProtocolError("unsupported", "transport.request")
            raise AssertionError("fallback must not probe")
        def close(self): self.closed = True
    created = []
    def build(config):
        item = Transport(config, fail=not created)
        created.append(item)
        return item
    monkeypatch.setattr(cli, "OpenMSXTransport", build)

    target = cli._build_live_target(tmp_path / "socket")

    assert not target.capabilities.persistent
    assert not target.capabilities.block_read
    assert len(created) == 2 and created[0].closed
