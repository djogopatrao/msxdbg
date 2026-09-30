import pytest

from msxdbg.debuginfo.index import ImageMapping, Project
from msxdbg.debuginfo.model import CodeLocation, Image, ImageId
from msxdbg.session.core import Session
from msxdbg.session.safety import SafetyGate
from msxdbg.session.state import SessionConfig, SessionState, SignatureSpec
from msxdbg.target.api import PageState, RegisterSet, TargetTimeout
from msxdbg.target.fake import FakeTarget
from msxdbg.ui.commands import WriteMemoryArguments, WriteRegisterArguments, build_registry


class Clock:
    def monotonic(self): return 0.0


def session(target, project=Project(()), config=SessionConfig()):
    value = Session(project, target, config, SafetyGate("phase10"), Clock())
    value.attach()
    return value


def test_memory_write_is_verified_and_replaces_the_stop_generation():
    target = FakeTarget(bytes(0x10000), RegisterSet({"PC": 0x1234, "SP": 0xF000}))
    active = session(target)
    old = active.where().snapshot
    result = active.write_memory(0x4000, bytes.fromhex("3412"))
    assert result.verified and result.observed == bytes.fromhex("3412")
    assert result.snapshot.stop_id > old.stop_id
    assert result.snapshot.memory_epoch > old.memory_epoch
    assert [call.operation for call in target.calls[-3:]] == [
        "write_memory", "read_memory", "read_registers"]


def test_uncertain_memory_write_is_not_retried_and_leaves_unknown_state():
    target = FakeTarget(bytes(0x10000), RegisterSet({"PC": 0x100}))
    active = session(target)
    target.inject_failure("write_memory", TargetTimeout(
        "timeout after send", "write_memory", outcome_unknown=True), after_apply=True)
    with pytest.raises(TargetTimeout):
        active.write_memory(0x2000, b"\xAA")
    assert active.state == SessionState.UNKNOWN
    assert target.read_memory(0x2000, 1) == b"\xAA"
    assert len([call for call in target.calls if call.operation == "write_memory"]) == 1


def test_failed_verification_after_accepted_write_is_explicitly_uncertain():
    target = FakeTarget(bytes(0x10000), RegisterSet({"PC": 0x100}))
    active = session(target)
    target.inject_failure("read_memory", TargetTimeout("read failed", "read_memory"))
    with pytest.raises(Exception) as caught:
        active.write_memory(0x2000, b"\x55")
    assert getattr(caught.value, "outcome_unknown", False)
    assert active.state == SessionState.UNKNOWN
    assert len([call for call in target.calls if call.operation == "write_memory"]) == 1


def test_register_half_write_preserves_other_half_and_rebuilds_snapshot():
    target = FakeTarget(bytes(0x10000), RegisterSet({"PC": 0x1234, "SP": 0xF000}))
    active = session(target)
    result = active.write_register("PCL", 0xAB)
    assert result.observed == 0xAB
    assert result.snapshot.registers.get("PC") == 0x12AB
    assert active.where().snapshot.stop_id == result.snapshot.stop_id


def test_signature_is_rearmed_when_overlapping_memory_is_written():
    memory = bytearray(0x10000); memory[0x200:0x202] = b"OK"
    target = FakeTarget(bytes(memory), RegisterSet({"PC": 0x100}))
    active = session(target, config=SessionConfig(signature=SignatureSpec(0x200, b"OK")))
    assert active.where().snapshot.signature_status == "verified"
    result = active.write_memory(0x201, b"X")
    assert result.snapshot.signature_status == "pending"


def test_mapper_evidence_selects_only_an_explicitly_associated_image():
    resident = ImageId("resident"); overlay = ImageId("overlay")
    location_a = CodeLocation(resident, 0x8000)
    location_b = CodeLocation(overlay, 0x8000)
    project = Project((Image(resident, locations=(location_a,)),
                       Image(overlay, locations=(location_b,))),
                      (ImageMapping(overlay, 2, "1", "2", "7"),))
    pages = tuple(PageState(i, "0", "0", "unknown") for i in range(4))
    pages = pages[:2] + (PageState(2, "1", "2", "7"),) + pages[3:]
    target = FakeTarget(bytes(0x10000), RegisterSet({"PC": 0x8000}), pages=pages)
    active = session(target, project)
    resolved = active.where().snapshot.pc_resolution
    assert resolved.status == "unique" and resolved.unique_or_none().image == overlay


def test_mapping_without_unique_evidence_preserves_ambiguity():
    a = ImageId("a"); b = ImageId("b")
    project = Project((Image(a, locations=(CodeLocation(a, 0x8000),)),
                       Image(b, locations=(CodeLocation(b, 0x8000),))),
                      (ImageMapping(a, 2, "1", segment="7"),
                       ImageMapping(b, 2, "1", segment="7")))
    pages = tuple(PageState(i, "1" if i == 2 else "0", "0", "7" if i == 2 else "unknown")
                  for i in range(4))
    target = FakeTarget(bytes(0x10000), RegisterSet({"PC": 0x8000}), pages=pages)
    assert session(target, project).where().snapshot.pc_resolution.status == "ambiguous"


def test_write_command_parser_requires_explicit_width_and_endianness_for_scalars():
    parser = build_registry().lookup("write").parser
    raw = parser("memory 0x8000 A55A")
    little = parser("memory 0x8000 0x1234 u16 little")
    big = parser("memory 0x8000 0x1234 u16 big")
    register = parser("register HL 0xCAFE")
    assert isinstance(raw, WriteMemoryArguments) and raw.data == b"\xA5\x5A"
    assert little.data == b"\x34\x12" and big.data == b"\x12\x34"
    assert isinstance(register, WriteRegisterArguments) and register.value == 0xCAFE
    with pytest.raises(ValueError): parser("memory 0xFFFF 0x100 u8")
