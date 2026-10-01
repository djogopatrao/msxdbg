from pathlib import Path

from msxdbg.__main__ import _diagnostic_lines, _diagnostic_summary
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


def test_default_diagnostics_are_summarized_by_category():
    diagnostics = (
        Diagnostic("load.unsupported-type", "warning", "one"),
        Diagnostic("load.unsupported-type", "warning", "two"),
        Diagnostic("load.unresolved-owner", "warning", "three"),
    )

    lines = _diagnostic_summary(diagnostics)

    assert lines[0] == ("warning: project loaded with 3 warnings "
                        "(unresolved symbols/modules: 1, unsupported types: 2)")
    assert lines[1] == "warning: use --verbose to show diagnostic details"
