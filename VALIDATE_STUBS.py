#!/usr/bin/env python3
"""Validate the recovered msxdbg package structure, syntax, and imports."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Tuple


ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "msxdbg"
SUBPACKAGES = ("debuginfo", "target", "session", "eval", "ui")
REQUIRED_PATHS = (
    PACKAGE / "__init__.py",
    *(PACKAGE / name / "__init__.py" for name in SUBPACKAGES),
    PACKAGE / "debuginfo" / "map_parser.py",
)


def python_files() -> List[Path]:
    """Return every Python source file in the package in stable order."""
    if not PACKAGE.is_dir():
        return []
    return sorted(PACKAGE.rglob("*.py"))


def module_name(path: Path) -> str:
    """Convert a package source path to its canonical import name."""
    parts = list(path.relative_to(ROOT).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def check_syntax(paths: Iterable[Path]) -> Tuple[int, int]:
    """Compile sources without executing them and report every result."""
    passed = 0
    failed = 0
    for path in paths:
        label = path.relative_to(ROOT)
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except (OSError, UnicodeError, SyntaxError) as error:
            print(f"FALHA sintaxe {label}: {error}")
            failed += 1
        else:
            print(f"OK sintaxe {label}")
            passed += 1
    return passed, failed


def check_imports(paths: Iterable[Path]) -> Tuple[int, int]:
    """Import each module in its own subprocess from the project root."""
    passed = 0
    failed = 0
    for path in paths:
        name = module_name(path)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    "import importlib; importlib.import_module(%r)" % name,
                ],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(f"FALHA import {name}: timeout após 10 segundos")
            failed += 1
            continue

        if result.returncode == 0:
            print(f"OK import {name}")
            passed += 1
        else:
            detail = (result.stderr or result.stdout).strip()
            print(f"FALHA import {name}: código {result.returncode}")
            if detail:
                print(detail)
            failed += 1
    return passed, failed


def main() -> int:
    """Run all structural checks and return a conventional status code."""
    missing = [path for path in REQUIRED_PATHS if not path.is_file()]
    for path in missing:
        print(f"FALHA ausente {path.relative_to(ROOT)}")

    files = python_files()
    syntax_paths = [Path(__file__).resolve(), *files]
    syntax_passed, syntax_failed = check_syntax(syntax_paths)
    import_passed, import_failed = check_imports(files)

    print(
        "Resumo: "
        f"sintaxe {syntax_passed} OK/{syntax_failed} falhas; "
        f"imports {import_passed} OK/{import_failed} falhas; "
        f"arquivos obrigatórios ausentes {len(missing)}"
    )
    return 1 if missing or syntax_failed or import_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
