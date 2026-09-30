from pathlib import Path

import pytest

from msxdbg.debuginfo.header_parser import HeaderInput, parse_headers
from msxdbg.debuginfo.loader import ImageSpec, ProjectLoader, ProjectSpec, read_project_spec
from msxdbg.debuginfo.macros import MacroContext
from msxdbg.debuginfo.model import ImageId
from msxdbg.debuginfo.model import ResolutionStatus, SourceSpan
from msxdbg.debuginfo.sources import SourceRepository
from msxdbg.session.memory_map import (MemoryLayoutPolicy, MemoryLimit,
                                       MemoryMapService)
from msxdbg.session.safety import (DangerousAction, InteractiveEntry,
                                   SafetyGate, SignatureGuard,
                                   SignatureStatus)
from msxdbg.session.state import SignatureSpec
from msxdbg.target.api import RegisterSet
from msxdbg.debuginfo.index import Project, SymbolContext


def test_source_repository_priority_window_cache_and_invalidation(tmp_path):
    first = tmp_path / "first"; second = tmp_path / "second"
    (first / "src").mkdir(parents=True); (second / "src").mkdir(parents=True)
    path = first / "src" / "main.c"; path.write_text("a\nb\nc\n")
    (second / "src" / "main.c").write_text("other\n")
    source = SourceSpan("src/main.c", "src/main.c", 2)
    repo = SourceRepository((first, second))
    assert repo.locate(source).status == ResolutionStatus.AMBIGUOUS
    (second / "src" / "main.c").unlink()
    assert repo.read_window(source, 1, 1).lines == ((1, "a"), (2, "b"), (3, "c"))
    path.write_text("x\ny\n")
    assert repo.read_window(source, 0, 0).lines == ((2, "y"),)
    repo.invalidate(path); repo.invalidate()


def test_source_repository_falls_back_to_listing_text(tmp_path):
    source = SourceSpan("missing.c", "missing.c", 7, "return 0;")
    window = SourceRepository((tmp_path,)).read_window(source, 2, 2)
    assert window.lines == ((7, "return 0;"),)
    assert window.diagnostics[0].code == "source.not-found"


def test_safety_gate_rejects_nonliteral_cross_action_and_replay():
    gate = SafetyGate("session")
    with pytest.raises(Exception):
        gate.authorize_typed(DangerousAction.RESET, InteractiveEntry("reset Yes", True))
    with pytest.raises(Exception):
        gate.authorize_typed(DangerousAction.RESET, InteractiveEntry("reset yes", False))
    permit = gate.authorize_typed(DangerousAction.RESET, InteractiveEntry("reset yes", True))
    with pytest.raises(Exception): gate.consume(permit, DangerousAction.LOAD)
    gate.consume(permit, DangerousAction.RESET)
    with pytest.raises(Exception): gate.consume(permit, DangerousAction.RESET)


def test_signature_guard_states_cache_and_rearm():
    class Reader:
        def __init__(self): self.data = b"no"; self.calls = 0
        def read_memory(self, address, size): self.calls += 1; return self.data
    reader = Reader(); guard = SignatureGuard(SignatureSpec(0x100, b"ok"))
    assert guard.check(reader) == SignatureStatus.PENDING
    reader.data = b"ok"
    assert guard.check(reader) == SignatureStatus.VERIFIED
    assert guard.check(reader) == SignatureStatus.VERIFIED and reader.calls == 2
    guard.rearm(); assert guard.check(reader) == SignatureStatus.VERIFIED and reader.calls == 3
    reader.calls = 0
    assert SignatureGuard(None).check(reader) == SignatureStatus.NOT_CONFIGURED
    assert reader.calls == 0


class Inspection:
    signature_status = "not-configured"
    symbol_context = SymbolContext(None, None, None, 0)
    registers = RegisterSet({"SP": 0xF000})
    def validate(self): pass
    def read_memory(self, address, size): return bytes((0x00, 0xE0))[:size]


def test_page3_known_unknown_and_corruption():
    service = MemoryMapService(); inspection = Inspection()
    report = service.page3(inspection, Project(()), MemoryLayoutPolicy(
        0xC000, 0x10000, MemoryLimit(address=0xD000), MemoryLimit()))
    assert report.free_size == 0x2000
    assert [item.name for item in report.regions] == ["data", "heap", "free", "stack", "reserved"]
    unknown = service.page3(inspection, Project(()), MemoryLayoutPolicy(
        0xC000, 0x10000, MemoryLimit(symbol="missing"), MemoryLimit()))
    assert unknown.free_size is None
    corrupt = service.page3(inspection, Project(()), MemoryLayoutPolicy(
        0xC000, 0x10000, MemoryLimit(address=0xF100), MemoryLimit()))
    assert corrupt.free_size is None and corrupt.warnings


def test_header_parser_struct_arrays_macros_and_independent_failure():
    result = parse_headers((HeaderInput(Path("types.h"), """
#define OFFSET 4
typedef struct { unsigned char x; unsigned int y; } Point;
typedef struct { Point items[OFFSET / 2]; } Pair;
typedef struct { int *bad; } Bad;
"""),))
    by_name = {item.name: item for item in result.value.types}
    assert by_name["Point"].size == 3
    assert by_name["Pair"].size == 6
    assert [item.name for item in result.value.macros] == ["OFFSET"]
    assert any(item.code == "header.invalid-struct" for item in result.diagnostics)


def test_versioned_manifest_resolves_relative_paths(tmp_path):
    manifest = tmp_path / "project.json"
    manifest.write_text('{"version":1,"images":[{"id":"game","out":"build","maps":["build/game.map"]}],"source_roots":["src"]}')
    spec = read_project_spec(manifest)
    assert spec.images[0].id.value == "game"
    assert spec.images[0].out == (tmp_path / "build").resolve()
    assert spec.images[0].maps == ((tmp_path / "build/game.map").resolve(),)
    assert spec.source_roots == ((tmp_path / "src").resolve(),)


def test_loader_integrates_header_types_and_macros(tmp_path):
    (tmp_path / "game.map").write_text("Value Global\n00008000 _main main\n")
    header = tmp_path / "types.h"
    header.write_text("#define SIZE 2\ntypedef struct { unsigned char bytes[SIZE]; } Header;\n")
    loaded = ProjectLoader().load(ProjectSpec(
        (ImageSpec(ImageId("game"), tmp_path),), struct_headers=(header,)))
    type_ = loaded.project.lookup_type("Header").unique_or_none()
    assert type_.size == 2 and type_.id.image == ImageId("game")
    assert loaded.macros.names(MacroContext()) == ("SIZE",)
