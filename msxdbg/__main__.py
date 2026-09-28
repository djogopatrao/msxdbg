"""CLI composition; the resolve path depends only on offline debug information."""
from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import sys
from typing import Optional, Sequence, Tuple

from .debuginfo.diagnostics import ProjectLoadError
from .debuginfo.loader import ImageSpec, ProjectLoader, ProjectSpec
from .debuginfo.model import ImageId


@dataclass(frozen=True)
class ResolveOptions:
    outputs: Tuple[Path, ...]
    target: str
    maps: Optional[Tuple[Path, ...]] = None


@dataclass(frozen=True)
class ShellOptions:
    outputs: Tuple[Path, ...]
    socket: Optional[Path] = None


@dataclass(frozen=True)
class ExecOptions:
    outputs: Tuple[Path, ...]
    commands: Tuple[str, ...]


def build_argument_parser() -> ArgumentParser:
    parser = ArgumentParser(prog='msxdbg')
    parser.add_argument('--version', action='store_true', help='show package version')
    subcommands = parser.add_subparsers(dest='command')
    resolve = subcommands.add_parser('resolve', help='resolve an address or source line offline')
    resolve.add_argument('--out', type=Path, action='append', required=True)
    resolve.add_argument('--map', type=Path, action='append', dest='maps')
    resolve.add_argument('target', help='[image::]0xADDR or [image::]file:line')
    return parser


def _target(raw):
    image = None
    if '::' in raw:
        qualifier, raw = raw.split('::', 1)
        if not qualifier or not raw or '::' in raw:
            raise ValueError('invalid image qualifier')
        image = ImageId(qualifier)
    if re.fullmatch(r'0[xX][0-9A-Fa-f]+', raw):
        address = int(raw, 16)
        if address > 0xFFFF:
            raise ValueError('address exceeds 16-bit CPU space')
        return image, address, None, None
    path, colon, line = raw.rpartition(':')
    if colon and path and re.fullmatch(r'[0-9]+', line) and int(line) > 0:
        return image, None, path, int(line)
    raise ValueError('resolve expects 0xADDR or file:line')


def _location_text(location):
    module = location.module.key if location.module else '?'
    text = f'0x{location.address:04X}  {module} (+0x{location.offset:04X})'
    if location.source:
        source = location.source
        text += f'  {source.path}:{source.line}: {source.text or ""}'
    return text.rstrip()


def run_resolve(options: ResolveOptions) -> int:
    try:
        image, address, path, line = _target(options.target)
        if not options.outputs:
            raise ValueError('at least one --out is required')
        if len({Path(out).resolve() for out in options.outputs}) != len(options.outputs):
            raise ValueError('duplicate --out directories')
        if options.maps is not None and len(options.outputs) != 1:
            raise ValueError('--map overrides require exactly one --out')
        names = Counter(Path(out).name for out in options.outputs)
        specs = tuple(ImageSpec(
            ImageId(Path(out).name if names[Path(out).name] == 1 else str(Path(out).resolve())),
            Path(out), options.maps) for out in options.outputs)
        loaded = ProjectLoader().load(ProjectSpec(specs))
        if image is not None and image not in {item.id for item in loaded.project.images}:
            raise ValueError('unknown image qualifier: ' + image.value)
        result = (loaded.project.resolve(address, image) if address is not None else
                  loaded.project.resolve_line(path, line, image))
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    except ProjectLoadError as exc:
        print(f'error: {exc}', file=sys.stderr)
        for diagnostic in exc.diagnostics:
            print(f'{diagnostic.code}: {diagnostic.message}', file=sys.stderr)
        return 1
    for diagnostic in loaded.diagnostics:
        print(f'warning: {diagnostic.code}: {diagnostic.message}', file=sys.stderr)
    if result.status == 'missing':
        print('unresolved: ' + options.target, file=sys.stderr)
        return 1
    if result.status == 'ambiguous':
        print('ambiguous: ' + options.target, file=sys.stderr)
        for candidate in result.candidates:
            location = candidate if address is not None else candidate.location
            print(f'  {location.image.value}::{_location_text(location)}', file=sys.stderr)
        return 1
    candidate = result.unique_or_none()
    if address is None:
        if candidate.effective_line != line:
            print(f'note: {path}:{line} has no code -- using line {candidate.effective_line}', file=sys.stderr)
        candidate = candidate.location
    print(_location_text(candidate))
    return 0


def run_shell(options: ShellOptions) -> int:
    raise NotImplementedError('run_shell is not implemented')


def run_exec(options: ExecOptions) -> int:
    raise NotImplementedError('run_exec is not implemented')


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_argument_parser()
    options = parser.parse_args(argv)
    if options.version:
        try:
            installed = version('msxdbg')
        except PackageNotFoundError:
            installed = 'development'
        print('msxdbg ' + installed)
        return 0
    if options.command == 'resolve':
        return run_resolve(ResolveOptions(tuple(options.out), options.target,
            tuple(options.maps) if options.maps is not None else None))
    parser.error('a command is required')


if __name__ == '__main__':
    raise SystemExit(main())
