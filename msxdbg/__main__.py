"""CLI composition contracts; importing this module performs no work."""
from __future__ import annotations
from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

@dataclass(frozen=True)
class ResolveOptions:
    outputs: Tuple[Path, ...]
    target: str
@dataclass(frozen=True)
class ShellOptions:
    outputs: Tuple[Path, ...]
    socket: Optional[Path] = None
@dataclass(frozen=True)
class ExecOptions:
    outputs: Tuple[Path, ...]
    commands: Tuple[str, ...]

def build_argument_parser() -> ArgumentParser: raise NotImplementedError("build_argument_parser is not implemented")
def run_resolve(options: ResolveOptions) -> int: raise NotImplementedError("run_resolve is not implemented")
def run_shell(options: ShellOptions) -> int: raise NotImplementedError("run_shell is not implemented")
def run_exec(options: ExecOptions) -> int: raise NotImplementedError("run_exec is not implemented")
def main(argv: Optional[Sequence[str]] = None) -> int: raise NotImplementedError("main is not implemented")

if __name__ == "__main__":
    raise SystemExit(main())
