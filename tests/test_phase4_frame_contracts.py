"""Phase 4 acceptance contracts backed by the synthetic FX-CPU fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest

from msxdbg.debuginfo.model import (
    CodeLocation,
    Function,
    FunctionId,
    Image,
    ImageId,
    ModuleId,
    Resolution,
    ResolutionStatus,
)
from msxdbg.debuginfo.index import Project
from msxdbg.session.frames import FrameService, FrameState
from msxdbg.session.core import Session
from msxdbg.session.execution import ExecutionKind, ExecutionRequest
from msxdbg.session.results import InvalidSessionState
from msxdbg.session.state import SessionConfig, SessionState, StopSnapshot
from msxdbg.target.api import Instruction, RegisterSet
from msxdbg.target.fake import FakeTarget


FIXTURE = Path(__file__).parent / "fixtures" / "cpu" / "frame_walk.json"


class FixtureReader:
    def __init__(self, data: dict, chain: str = "three_frames") -> None:
        self.data = data
        self.memory = bytearray(0x10000)
        for word in data["frame_chains"][chain]:
            ix = word["ix"]
            self.memory[ix : ix + 2] = word["caller_ix"].to_bytes(2, "little")
            self.memory[ix + 2 : ix + 4] = word["return_address"].to_bytes(2, "little")
        self.instructions = tuple(
            Instruction(
                item["address"],
                len(bytes.fromhex(item["bytes"])),
                item["text"],
                bytes.fromhex(item["bytes"]),
            )
            for item in data["instructions"]
        )
        self.project = Project((Image(
            ImageId("phase4"),
            functions=tuple(make_function(item) for item in data["functions"]),
        ),))

    def read_memory(self, address: int, size: int) -> bytes:
        if address < 0 or size < 0 or address + size > 0x10000:
            raise ValueError("memory range outside CPU address space")
        return bytes(self.memory[address : address + size])

    def disassemble(self, address: int, count: int):
        candidates = tuple(item for item in self.instructions if item.address >= address)
        return candidates[:count]

    def function_at(self, address: int):
        """Resolution hook required by the frame walker but absent from FrameReader today."""
        return self.project.function_at(address)


class FrameTarget(FakeTarget):
    def __init__(self, reader: FixtureReader, registers: RegisterSet) -> None:
        super().__init__(bytes(reader.memory), registers)
        self.instructions = reader.instructions

    def disassemble(self, address: int, count: int):
        failure = self._begin("disassemble", address, count)
        candidates = tuple(item for item in self.instructions if item.address >= address)
        result = candidates[:count]
        self._finish(failure)
        return result


class Clock:
    def monotonic(self): return 0.0
    def sleep(self, seconds): return None


class NeverCancelled:
    def is_cancelled(self): return False


@pytest.fixture
def cpu_fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_function(spec: dict) -> Function:
    image = ImageId("phase4")
    module = ModuleId(image, "frames")
    return Function(
        FunctionId(module, spec["name"]),
        spec["name"],
        spec["entry"],
        spec["end"],
    )


def make_snapshot(data: dict, pc: Optional[int] = None) -> StopSnapshot:
    image = ImageId("phase4")
    module = ModuleId(image, "frames")
    pc = data["registers"]["PC"] if pc is None else pc
    location = CodeLocation(
        image,
        pc,
        module=module,
        function=FunctionId(module, "leaf"),
    )
    return StopSnapshot(
        1,
        0,
        RegisterSet({**data["registers"], "PC": pc}),
        Resolution(ResolutionStatus.UNIQUE, (location,)),
        "not-configured",
    )


def make_session(data: dict):
    reader = FixtureReader(data)
    target = FrameTarget(reader, RegisterSet(data["registers"]))
    session = Session(reader.project, target, SessionConfig(), object(), Clock())
    return session, target


def test_fx_cpu_encodes_little_endian_ix_chain_and_independent_oracle(cpu_fixture):
    reader = FixtureReader(cpu_fixture)
    first = cpu_fixture["frame_chains"]["three_frames"][0]
    raw = reader.read_memory(first["ix"], 4)
    assert int.from_bytes(raw[:2], "little") == first["caller_ix"]
    assert int.from_bytes(raw[2:], "little") == first["return_address"]
    assert cpu_fixture["expectations"]["three_frames"]["scope_pcs"] == [
        pc - 1 if index else pc
        for index, pc in enumerate(cpu_fixture["expectations"]["three_frames"]["pcs"])
    ]


def test_frame_state_recognizes_exact_sdcc_prologue(cpu_fixture):
    reader = FixtureReader(cpu_fixture)
    leaf = make_function(cpu_fixture["functions"][0])
    assert FrameService().frame_state(leaf, 0x1108, reader) == FrameState.IX_ACTIVE


def test_frame_state_distinguishes_before_prologue_epilogue_and_frameless(cpu_fixture):
    reader = FixtureReader(cpu_fixture)
    leaf = make_function(cpu_fixture["functions"][0])
    frameless = make_function(cpu_fixture["functions"][3])
    assert FrameService().frame_state(leaf, leaf.entry, reader) == FrameState.UNKNOWN
    assert FrameService().frame_state(leaf, 0x111A, reader) != FrameState.IX_ACTIVE
    assert FrameService().frame_state(frameless, frameless.entry, reader) == FrameState.FRAMELESS


def test_frame_state_is_conservative_for_truncated_or_malformed_prologue(cpu_fixture):
    leaf = make_function(cpu_fixture["functions"][0])
    truncated = FixtureReader(cpu_fixture)
    truncated.instructions = truncated.instructions[:1]
    assert FrameService().frame_state(leaf, 0x1108, truncated) == FrameState.UNKNOWN

    malformed = FixtureReader(cpu_fixture)
    instructions = list(malformed.instructions)
    second = instructions[1]
    instructions[1] = Instruction(second.address, 1, "nop", b"\x00")
    malformed.instructions = tuple(instructions)
    assert FrameService().frame_state(leaf, 0x1108, malformed) == FrameState.UNKNOWN


def test_frame_state_rejects_invalid_pc_and_does_not_classify_outside_function(cpu_fixture):
    reader = FixtureReader(cpu_fixture)
    leaf = make_function(cpu_fixture["functions"][0])
    assert FrameService().frame_state(leaf, leaf.end, reader) == FrameState.UNKNOWN
    with pytest.raises(ValueError, match="CPU address"):
        FrameService().frame_state(leaf, -1, reader)


@pytest.mark.parametrize(
    ("chain", "expected_reason"),
    (
        ("cycle", "frame-pointer-cycle"),
        ("unknown_caller", "unknown-caller"),
        ("invalid_return", "invalid-return-address"),
    ),
)
def test_frame_walk_terminates_safely_for_bad_chains(cpu_fixture, chain, expected_reason):
    """The future walker must expose a stable reason instead of guessing a caller."""
    reader = FixtureReader(cpu_fixture, chain)
    result = FrameService().walk(make_snapshot(cpu_fixture), reader)
    assert result.termination_reason == expected_reason


def test_frame_walk_preserves_display_pc_and_scope_pc(cpu_fixture):
    reader = FixtureReader(cpu_fixture)
    result = FrameService().walk(make_snapshot(cpu_fixture), reader)
    expected = cpu_fixture["expectations"]["three_frames"]
    assert [frame.pc for frame in result.frames] == expected["pcs"]
    assert [frame.scope_pc for frame in result.frames] == expected["scope_pcs"]


def test_frame_walk_handles_zero_and_one_caller(cpu_fixture):
    no_caller = FixtureReader(cpu_fixture)
    result = FrameService().walk(make_snapshot(cpu_fixture, 0x1400), no_caller)
    assert len(result.frames) == 1
    assert result.frames[0].state == FrameState.FRAMELESS
    assert result.termination_reason == "current-frame-not-active"

    one_caller = FixtureReader(cpu_fixture)
    ix = cpu_fixture["registers"]["IX"]
    one_caller.memory[ix : ix + 2] = (0).to_bytes(2, "little")
    one_caller.memory[ix + 2 : ix + 4] = (0x1211).to_bytes(2, "little")
    result = FrameService().walk(make_snapshot(cpu_fixture), one_caller)
    assert len(result.frames) == 2
    assert result.frames[1].pc == 0x1211
    assert result.frames[1].scope_pc == 0x1210
    assert result.termination_reason == "caller-frame-state-unknown"


def test_frame_walk_appends_frameless_caller_before_stopping(cpu_fixture):
    reader = FixtureReader(cpu_fixture)
    ix = cpu_fixture["registers"]["IX"]
    reader.memory[ix : ix + 2] = (0x9020).to_bytes(2, "little")
    reader.memory[ix + 2 : ix + 4] = (0x1401).to_bytes(2, "little")
    result = FrameService().walk(make_snapshot(cpu_fixture), reader)
    assert len(result.frames) == 2
    assert result.frames[1].state == FrameState.FRAMELESS
    assert result.termination_reason == "caller-without-ix-frame"


def test_frame_walk_stops_at_configured_limit(cpu_fixture):
    reader = FixtureReader(cpu_fixture)
    first_ix = cpu_fixture["registers"]["IX"]
    for index in range(65):
        ix = first_ix + index * 4
        caller_ix = first_ix + (index + 1) * 4
        reader.memory[ix : ix + 2] = caller_ix.to_bytes(2, "little")
        reader.memory[ix + 2 : ix + 4] = (0x1211).to_bytes(2, "little")
    result = FrameService().walk(make_snapshot(cpu_fixture), reader)
    assert len(result.frames) == 64
    assert result.termination_reason == "frame-limit"


def test_session_caches_backtrace_and_inspection_uses_selected_frame(cpu_fixture):
    session, target = make_session(cpu_fixture)
    assert session.attach() == SessionState.STOPPED
    trace = session.backtrace()
    calls_after_first_walk = tuple(target.calls)
    assert len(trace.frames) == 3
    assert session.backtrace() == trace
    assert target.calls == calls_after_first_walk

    selected = session.select_frame(1)
    inspection = session.inspection()
    assert inspection.frame == selected
    assert inspection.symbol_context.pc == selected.scope_pc
    assert target.calls == calls_after_first_walk


def test_invalid_frame_selection_preserves_previous_selection(cpu_fixture):
    session, _ = make_session(cpu_fixture)
    session.attach()
    selected = session.select_frame(1)
    with pytest.raises(IndexError, match="out of range"):
        session.select_frame(99)
    assert session.inspection().frame == selected
    with pytest.raises(ValueError, match="integer"):
        session.select_frame(True)
    assert session.inspection().frame == selected


def test_new_stop_invalidates_frames_and_resets_selection(cpu_fixture):
    session, target = make_session(cpu_fixture)
    session.attach()
    session.select_frame(1)
    calls_before_execution = len(target.calls)
    session.execute(ExecutionRequest(ExecutionKind.STEPI), NeverCancelled())
    assert session.inspection().frame.index == 0
    assert session.inspection().stop_id == session.where().snapshot.stop_id
    assert len(target.calls) > calls_before_execution


def test_session_rejects_backtrace_and_selection_while_not_stopped(cpu_fixture):
    session, _ = make_session(cpu_fixture)
    with pytest.raises(InvalidSessionState, match="stopped"):
        session.backtrace()
    with pytest.raises(InvalidSessionState, match="stopped"):
        session.select_frame(0)
