"""Opt-in integration tests against an operator-prepared openMSX instance.

These tests never launch openMSX, change media, reset, or load a state.
See README.md in this directory for the explicit opt-in variables.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from msxdbg.target.api import ExecutionStatus, TargetCapabilities
from msxdbg.target.openmsx import OpenMSXTarget
from msxdbg.target.transport import OpenMSXTransport, TransportConfig, discover_socket
from msxdbg.debuginfo.loader import ImageSpec, ProjectLoader, ProjectSpec
from msxdbg.debuginfo.model import ImageId
from msxdbg.session.core import Session
from msxdbg.session.safety import SafetyGate
from msxdbg.session.state import SessionConfig, SessionState


LIVE_SOCKET = os.environ.get("MSXDBG_LIVE_SOCKET")
ALLOW_BREAKPOINTS = os.environ.get("MSXDBG_LIVE_BREAKPOINTS") == "1"
ALLOW_EXECUTION = os.environ.get("MSXDBG_LIVE_EXECUTION") == "1"
ALLOW_OPTIMIZATIONS = os.environ.get("MSXDBG_LIVE_OPTIMIZATIONS") == "1"
LIVE_OUT = os.environ.get("MSXDBG_LIVE_OUT")
ALLOW_MSXGL_FIXTURE = os.environ.get("MSXDBG_LIVE_MSXGL_FIXTURE") == "1"

pytestmark = pytest.mark.live


def _target() -> OpenMSXTarget:
    socket_path = discover_socket(Path(LIVE_SOCKET))
    transport = OpenMSXTransport(TransportConfig(socket_path, 5.0))
    return OpenMSXTarget(transport, TargetCapabilities())


def _require_stopped(target: OpenMSXTarget) -> None:
    if target.execution_status() != ExecutionStatus.STOPPED:
        pytest.skip("live openMSX must be paused by the operator")


class _LiveClock:
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


def _msxgl_fixture():
    root = Path(__file__).resolve().parents[2]
    return root, root / "tests" / "fixtures" / "msxgl_debug"


def _run_msxgl_exec(*commands):
    root, fixture = _msxgl_fixture()
    command = (
        sys.executable, "-m", "msxdbg", "exec",
        "--out", str(fixture / "out"),
        "--source-root", str(fixture),
        "--socket", LIVE_SOCKET,
        "--json", "--timeout", "10",
    ) + tuple(item for text in commands for item in ("-c", text))
    completed = subprocess.run(
        command, cwd=root, text=True, capture_output=True, timeout=120,
        check=False,
    )
    assert completed.returncode == 0, (
        f"stderr:\n{completed.stderr}\nstdout:\n{completed.stdout}")
    return [json.loads(line) for line in completed.stdout.splitlines()]


@pytest.mark.skipif(not LIVE_SOCKET, reason="MSXDBG_LIVE_SOCKET is not set")
def test_live_read_only_target_contract():
    target = _target()
    try:
        _require_stopped(target)
        registers = target.read_registers()
        pc = registers.get("PC")
        size = min(16, 0x10000 - pc)

        memory = target.read_memory(pc, size)
        instructions = target.disassemble(pc, 1)
        pages = target.read_pages()
        breakpoints = target.list_breakpoints()

        assert len(memory) == size
        assert len(instructions) == 1 and instructions[0].address == pc
        assert len(pages) == 4
        assert all(0 <= item.address <= 0xFFFF for item in breakpoints)
    finally:
        target.close()


@pytest.mark.skipif(
    not (LIVE_SOCKET and LIVE_OUT),
    reason="MSXDBG_LIVE_SOCKET and MSXDBG_LIVE_OUT are required",
)
def test_live_exec_json_read_only():
    root = Path(__file__).resolve().parents[2]
    command = (
        sys.executable, "-m", "msxdbg", "exec",
        "--out", LIVE_OUT,
        "--socket", LIVE_SOCKET,
        "--json", "--timeout", "10",
        "-c", "where",
        "-c", "info registers",
    )

    completed = subprocess.run(
        command, cwd=root, text=True, capture_output=True, timeout=120,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    envelopes = [json.loads(line) for line in completed.stdout.splitlines()]
    assert [item["command"] for item in envelopes] == ["where", "info"]
    assert all(item["ok"] for item in envelopes)


@pytest.mark.skipif(
    not (LIVE_SOCKET and ALLOW_BREAKPOINTS),
    reason="MSXDBG_LIVE_BREAKPOINTS=1 is required",
)
def test_live_breakpoint_create_list_remove():
    target = _target()
    remote_id = None
    try:
        _require_stopped(target)
        address = target.read_registers().get("PC")
        remote_id = target.create_breakpoint(address)

        matching = [item for item in target.list_breakpoints()
                    if item.id == remote_id]
        assert len(matching) == 1 and matching[0].address == address
    finally:
        if remote_id is not None:
            target.remove_breakpoint(remote_id)
        target.close()


@pytest.mark.skipif(
    not (LIVE_SOCKET and ALLOW_EXECUTION),
    reason="MSXDBG_LIVE_EXECUTION=1 is required",
)
def test_live_single_instruction_step():
    target = _target()
    try:
        _require_stopped(target)
        target.step_into()
        deadline = time.monotonic() + 5.0
        while target.execution_status() != ExecutionStatus.STOPPED:
            if time.monotonic() >= deadline:
                pytest.fail("openMSX did not stop after step_in")
            time.sleep(0.05)
        assert 0 <= target.read_registers().get("PC") <= 0xFFFF
    finally:
        target.close()


@pytest.mark.skipif(
    not (LIVE_SOCKET and ALLOW_OPTIMIZATIONS),
    reason="MSXDBG_LIVE_OPTIMIZATIONS=1 is required",
)
def test_live_persistent_connection_and_block_read():
    socket_path = discover_socket(Path(LIVE_SOCKET))
    legacy_transport = OpenMSXTransport(TransportConfig(socket_path, 15.0))
    optimized_transport = OpenMSXTransport(TransportConfig(
        socket_path, 15.0, "persistent"
    ))
    legacy = OpenMSXTarget(legacy_transport, TargetCapabilities())
    optimized = OpenMSXTarget(
        optimized_transport,
        TargetCapabilities(persistent=True, block_read=True),
    )
    try:
        _require_stopped(optimized)
        pc = optimized.read_registers().get("PC")
        size = min(256, 0x10000 - pc)

        expected = legacy.read_memory(pc, size)
        actual = optimized.read_memory(pc, size)
        whole_memory = optimized.read_memory(0, 0x10000)

        assert actual == expected
        assert b"\x00" in whole_memory and b"\xff" in whole_memory
        assert optimized_transport.stats.connections == 1
        assert optimized_transport.stats.requests >= 4
        assert legacy_transport.stats.connections == 1
    finally:
        legacy.close()
        optimized.close()


@pytest.mark.skipif(
    not (LIVE_SOCKET and ALLOW_EXECUTION and ALLOW_MSXGL_FIXTURE),
    reason=("MSXDBG_LIVE_SOCKET, MSXDBG_LIVE_EXECUTION=1 and "
            "MSXDBG_LIVE_MSXGL_FIXTURE=1 are required"),
)
def test_live_msxgl_source_breakpoint_stops_at_compiled_line():
    envelopes = _run_msxgl_exec(
        "break debug_fixture.c:17", "continue", "where")
    stop = envelopes[1]["data"]
    assert stop["matching_breakpoints"] == [1]
    assert stop["location"]["source"]["path"].endswith("debug_fixture.c")
    assert stop["location"]["source"]["line"] == 17


@pytest.mark.skipif(
    not (LIVE_SOCKET and ALLOW_EXECUTION and ALLOW_MSXGL_FIXTURE),
    reason=("MSXDBG_LIVE_SOCKET, MSXDBG_LIVE_EXECUTION=1 and "
            "MSXDBG_LIVE_MSXGL_FIXTURE=1 are required"),
)
def test_live_issue_3_list_requested_and_current_source_lines():
    envelopes = _run_msxgl_exec(
        "break debug_fixture.c:17", "continue",
        "list debug_fixture.c:16", "list")

    requested = envelopes[2]["data"]
    current = envelopes[3]["data"]
    assert requested["focal_line"] == 16
    assert requested["path"].endswith("debug_fixture.c")
    assert current["focal_line"] == 17
    assert current["path"].endswith("debug_fixture.c")


@pytest.mark.skipif(
    not (LIVE_SOCKET and ALLOW_BREAKPOINTS and ALLOW_MSXGL_FIXTURE),
    reason=("MSXDBG_LIVE_SOCKET, MSXDBG_LIVE_BREAKPOINTS=1 and "
            "MSXDBG_LIVE_MSXGL_FIXTURE=1 are required"),
)
def test_live_issue_4_info_breakpoints_includes_source_location():
    envelopes = _run_msxgl_exec(
        "break debug_fixture.c:17", "info breakpoints")

    breakpoint = envelopes[1]["data"]["breakpoints"][0]
    assert breakpoint["address"] == 0x4065
    assert breakpoint["location"]["source"]["path"].endswith(
        "debug_fixture.c")
    assert breakpoint["location"]["source"]["line"] == 17


@pytest.mark.skipif(
    not (LIVE_SOCKET and ALLOW_EXECUTION and ALLOW_MSXGL_FIXTURE),
    reason=("MSXDBG_LIVE_SOCKET, MSXDBG_LIVE_EXECUTION=1 and "
            "MSXDBG_LIVE_MSXGL_FIXTURE=1 are required"),
)
def test_live_issue_7_backtrace_after_external_stop():
    root, fixture = _msxgl_fixture()
    loaded = ProjectLoader().load(ProjectSpec((ImageSpec(
        ImageId("msxgl-debug"), fixture / "out"),), (fixture,)))
    target = _target()
    session = Session(loaded.project, target, SessionConfig(),
                      SafetyGate(), _LiveClock())
    try:
        assert session.attach() == SessionState.STOPPED
        session.invalidate()
        target.continue_execution()
        time.sleep(0.05)
        target.interrupt()
        deadline = time.monotonic() + 5.0
        while target.execution_status() != ExecutionStatus.STOPPED:
            if time.monotonic() >= deadline:
                pytest.fail("openMSX did not acknowledge the external stop")
            time.sleep(0.05)

        trace = session.backtrace()

        assert session.state == SessionState.STOPPED
        assert trace.frames
        assert trace.frames[0].pc == session.where().snapshot.registers.get("PC")
    finally:
        target.close()
