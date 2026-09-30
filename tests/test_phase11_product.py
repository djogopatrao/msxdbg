from pathlib import Path

from msxdbg.__main__ import _diagnostic_lines
from msxdbg.debuginfo.diagnostics import Diagnostic, Origin


def test_repeated_diagnostics_are_aggregated_without_losing_origins():
    diagnostics = (
        Diagnostic("load.example", "warning", "same issue",
                   (Origin(Path("a.lst"), 2, "listing"),)),
        Diagnostic("load.example", "warning", "same issue",
                   (Origin(Path("b.lst"), 3, "listing"),)),
    )

    lines = _diagnostic_lines(diagnostics, prefix="")

    assert lines[0] == "warning: load.example: same issue (2 occurrences)"
    assert "a.lst:2" in lines[1]
    assert "b.lst:3" in lines[2]


def test_package_metadata_declares_console_entry_point():
    metadata = Path("pyproject.toml").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.10"' in metadata
    assert 'msxdbg = "msxdbg.__main__:main"' in metadata
    assert 'version = "0.11.0rc1"' in metadata
