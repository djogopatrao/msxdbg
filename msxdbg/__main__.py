"""CLI composition; the resolve path depends only on offline debug information."""
from __future__ import annotations

from argparse import ArgumentParser
from collections import Counter
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import re
import sys
import time
from typing import Optional, Sequence, Tuple

from .debuginfo.diagnostics import ProjectLoadError
from .debuginfo.loader import ImageSpec, ProjectLoader, ProjectSpec, read_project_spec
from .debuginfo.model import ImageId
from .debuginfo.macros import MacroContext
from .eval.evaluator import Evaluator
from .eval.values import ValueDecoder, ValueLimits
from .session.core import Session
from .session.safety import SafetyGate
from .session.state import SessionConfig, SignatureSpec, StepMode
from .target.api import TargetCapabilities, TargetError
from .target.openmsx import OpenMSXTarget
from .target.transport import (ConnectionMode, OpenMSXTransport, TransportConfig,
                               discover_socket)
from .ui.application import CommandApplication
from .ui.batch import BatchPolicy, BatchRunner
from .ui.commands import (CommandContext, DisassemblyCursor, NavigationState,
                          SourceCursor)


@dataclass(frozen=True)
class ResolveOptions:
    outputs: Tuple[Path, ...]
    target: str
    maps: Optional[Tuple[Path, ...]] = None
    project: Optional[Path] = None
    verbose: bool = False


@dataclass(frozen=True)
class ShellOptions:
    outputs: Tuple[Path, ...]
    socket: Optional[Path] = None
    maps: Optional[Tuple[Path, ...]] = None
    cdbs: Optional[Tuple[Path, ...]] = None
    source_roots: Tuple[Path, ...] = ()
    struct_headers: Tuple[Path, ...] = ()
    signature: Optional[SignatureSpec] = None
    mode: StepMode = StepMode.SOURCE
    project: Optional[Path] = None
    verbose: bool = False


@dataclass(frozen=True)
class ExecOptions:
    outputs: Tuple[Path, ...]
    commands: Tuple[str, ...]
    timeout_seconds: float = 30.0
    socket: Optional[Path] = None
    maps: Optional[Tuple[Path, ...]] = None
    cdbs: Optional[Tuple[Path, ...]] = None
    source_roots: Tuple[Path, ...] = ()
    struct_headers: Tuple[Path, ...] = ()
    signature: Optional[SignatureSpec] = None
    mode: StepMode = StepMode.SOURCE
    project: Optional[Path] = None
    verbose: bool = False


def build_argument_parser() -> ArgumentParser:
    parser = ArgumentParser(prog='msxdbg')
    parser.add_argument('--version', action='store_true', help='show package version')
    subcommands = parser.add_subparsers(dest='command')
    resolve = subcommands.add_parser('resolve', help='resolve an address or source line offline')
    resolve_source = resolve.add_mutually_exclusive_group(required=True)
    resolve_source.add_argument('--out', type=Path, action='append')
    resolve_source.add_argument('--project', type=Path)
    resolve.add_argument('--map', type=Path, action='append', dest='maps')
    resolve.add_argument('-v', '--verbose', action='store_true')
    resolve.add_argument('target', help='[image::]0xADDR or [image::]file:line')
    def live(name, help_text):
        command = subcommands.add_parser(name, help=help_text)
        source = command.add_mutually_exclusive_group(required=True)
        source.add_argument('--out', type=Path, action='append')
        source.add_argument('--project', type=Path)
        command.add_argument('--map', type=Path, action='append', dest='maps')
        command.add_argument('--cdb', type=Path, action='append', dest='cdbs')
        command.add_argument('--socket', type=Path)
        command.add_argument('--source-root', type=Path, action='append', default=[])
        command.add_argument('--struct-header', type=Path, action='append', default=[])
        command.add_argument('--verify-signature', type=_signature)
        command.add_argument('--mode', choices=('c', 'source', 'asm', 'assembly'), default='c')
        command.add_argument('-v', '--verbose', action='store_true')
        return command
    live('shell', 'attach an interactive debugger to openMSX')
    execute = live('exec', 'execute debugger commands and emit JSON Lines')
    execute.add_argument('-c', '--command', action='append', required=True, dest='commands')
    execute.add_argument('--json', action='store_true', required=True)
    execute.add_argument('--timeout', type=_positive_timeout, default=30.0)
    return parser


def _positive_timeout(raw: str) -> float:
    try: value = float(raw)
    except ValueError: raise ValueError('timeout must be a positive number') from None
    if value <= 0: raise ValueError('timeout must be a positive number')
    return value


def _signature(raw: str) -> SignatureSpec:
    address, separator, encoded = raw.partition('=')
    if not separator or not re.fullmatch(r'0[xX][0-9A-Fa-f]+', address):
        raise ValueError('signature must use 0xADDR=HEXBYTES')
    if not encoded or len(encoded) % 2 or not re.fullmatch(r'[0-9A-Fa-f]+', encoded):
        raise ValueError('signature bytes must be non-empty even-length hexadecimal')
    return SignatureSpec(int(address, 16), bytes.fromhex(encoded))


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


def _diagnostic_lines(diagnostics, prefix: str = "warning"):
    """Aggregate repeated diagnostics while retaining every distinct origin."""
    grouped = {}
    for diagnostic in diagnostics:
        key = (diagnostic.code, diagnostic.severity, diagnostic.message)
        entry = grouped.setdefault(key, [0, []])
        entry[0] += 1
        for origin in diagnostic.origins:
            marker = (origin.path, origin.line, origin.record_kind)
            if marker not in entry[1]:
                entry[1].append(marker)
    lines = []
    for (code, severity, message), (count, origins) in grouped.items():
        label = prefix if prefix else severity
        suffix = f" ({count} occurrences)" if count > 1 else ""
        lines.append(f"{label}: {code}: {message}{suffix}")
        for path, line, record_kind in origins:
            location = str(path) + (f":{line}" if line is not None else "")
            lines.append(f"  origin: {location} [{record_kind}]")
    return tuple(lines)


def _diagnostic_category(code: str) -> str:
    if "unsupported-type" in code or "invalid-type" in code:
        return "unsupported types"
    if any(part in code for part in ("unresolved", "missing-symbol", "missing-module")):
        return "unresolved symbols/modules"
    if any(part in code for part in ("address", "relocation", "base-conflict", "link-conflict")):
        return "address/relocation conflicts"
    if any(part in code for part in ("source", "listing", "lst.")):
        return "source/listing information"
    if any(part in code for part in ("header", "macro")):
        return "headers/macros"
    if any(part in code for part in ("parse", "invalid-record", "unreadable-artifact")):
        return "artifact parsing"
    return "other"


def _diagnostic_summary(diagnostics, successful: bool = True) -> Tuple[str, ...]:
    diagnostics = tuple(diagnostics)
    if not diagnostics:
        return ()
    categories = Counter(_diagnostic_category(item.code) for item in diagnostics)
    detail = ", ".join(f"{name}: {count}" for name, count in sorted(categories.items()))
    headline = (f"warning: project loaded with {len(diagnostics)} warnings"
                if successful else f"warning: {len(diagnostics)} project diagnostics")
    return (f"{headline} ({detail})",
            "warning: use --verbose to show diagnostic details")


def run_resolve(options: ResolveOptions) -> int:
    try:
        image, address, path, line = _target(options.target)
        if options.project is not None:
            if options.outputs or options.maps is not None:
                raise ValueError('--project cannot be combined with --out or --map')
            spec = read_project_spec(options.project)
            loaded = ProjectLoader().load(spec)
            image_ids = {item.id for item in loaded.project.images}
            if image is not None and image not in image_ids:
                raise ValueError('unknown image qualifier: ' + image.value)
            result = (loaded.project.resolve(address, image) if address is not None else
                      loaded.project.resolve_line(path, line, image))
        else:
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
        lines = (_diagnostic_lines(exc.diagnostics, prefix="") if options.verbose
                 else _diagnostic_summary(exc.diagnostics, successful=False))
        for line in lines: print(line, file=sys.stderr)
        return 1
    lines = (_diagnostic_lines(loaded.diagnostics) if options.verbose
             else _diagnostic_summary(loaded.diagnostics))
    for line in lines:
        print(line, file=sys.stderr)
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


class _SystemClock:
    def monotonic(self) -> float: return time.monotonic()
    def sleep(self, seconds: float) -> None: time.sleep(seconds)


def _project_spec(outputs, maps=None, cdbs=None, source_roots=(), struct_headers=()):
    if not outputs:
        raise ValueError('at least one --out is required')
    resolved = [Path(output).resolve() for output in outputs]
    if len(set(resolved)) != len(resolved):
        raise ValueError('duplicate --out directories')
    if len(outputs) != 1 and (maps is not None or cdbs is not None):
        raise ValueError('--map/--cdb overrides require exactly one --out')
    names = Counter(Path(output).name for output in outputs)
    images = tuple(ImageSpec(
        ImageId(Path(output).name if names[Path(output).name] == 1
                else str(Path(output).resolve())),
        Path(output), maps, cdbs,
    ) for output in outputs)
    return ProjectSpec(images, tuple(source_roots), tuple(struct_headers))


def _compose_context(options, input_origin: str):
    if options.project is not None:
        if (options.outputs or options.maps is not None or options.cdbs is not None
                or options.source_roots or options.struct_headers):
            raise ValueError('--project cannot be combined with --out, --map, --cdb, --source-root, or --struct-header')
        spec = read_project_spec(options.project)
    else:
        spec = _project_spec(options.outputs, options.maps, options.cdbs,
                             options.source_roots, options.struct_headers)
    loaded = ProjectLoader().load(spec)
    socket_path = discover_socket(options.socket)
    target = _build_live_target(socket_path)
    timeout = options.timeout_seconds if isinstance(options, ExecOptions) else None
    session = Session(loaded.project, target,
        SessionConfig(options.signature, options.mode, execution_timeout=timeout),
        SafetyGate(), _SystemClock())
    evaluator = Evaluator(loaded.project, ValueDecoder(), ValueLimits())
    context = CommandContext(session, loaded.project, loaded.sources, loaded.macros,
        MacroContext(), evaluator, NavigationState(SourceCursor(), DisassemblyCursor()),
        input_origin, timeout)
    return loaded, context


def _build_live_target(socket_path: Path) -> OpenMSXTarget:
    """Select optimized transport only after read-only capability probes."""
    optimized = OpenMSXTransport(TransportConfig(
        socket_path, 5.0, ConnectionMode.PERSISTENT
    ))
    features = (None, None, None)
    try:
        first = optimized.request("expr 0")
        second = optimized.request("expr 0")
        block = optimized.request(
            "binary encode hex [debug read_block memory 0 1]"
        )
        if ((first.status, first.text.strip()) != ("ok", "0")
                or (second.status, second.text.strip()) != ("ok", "0")
                or block.status != "ok"
                or not re.fullmatch(r"[0-9A-Fa-f]{2}", block.text.strip())):
            raise ValueError("openMSX optimization probe was rejected")
        features = _probe_debug_features(optimized)
    except (TargetError, ValueError):
        optimized.close()
        fallback = OpenMSXTransport(TransportConfig(socket_path, 5.0))
        return OpenMSXTarget(fallback, TargetCapabilities(
            conditional_breakpoints=False, watchpoints=False,
            mapping_conditions=False))
    return OpenMSXTarget(
        optimized, TargetCapabilities(persistent=True, block_read=True,
            conditional_breakpoints=features[0], watchpoints=features[1],
            mapping_conditions=features[2])
    )


def _probe_debug_features(transport: OpenMSXTransport):
    """Probe extension syntax without creating or modifying debug points."""
    breakpoint = transport.request("help debug breakpoint create")
    watchpoint = transport.request("help debug watchpoint create")
    slot = transport.request("help get_selected_slot")
    conditional = breakpoint.status == "ok" and "-condition" in breakpoint.text
    watches = (watchpoint.status == "ok" and "read_mem" in watchpoint.text
               and "write_mem" in watchpoint.text)
    mapping = conditional and slot.status == "ok"
    return conditional, watches, mapping


def _report_diagnostics(loaded, verbose: bool = False) -> None:
    lines = (_diagnostic_lines(loaded.diagnostics, prefix="") if verbose
             else _diagnostic_summary(loaded.diagnostics))
    for line in lines:
        print(line, file=sys.stderr)


def _run_live(options, batch: bool) -> int:
    context = None
    try:
        loaded, context = _compose_context(options, 'batch' if batch else 'interactive')
        _report_diagnostics(loaded, options.verbose)
        context.session.attach()
        application = (CommandApplication(batch=BatchRunner(
            policy=BatchPolicy(options.timeout_seconds))) if batch else CommandApplication())
        if batch:
            return application.run_exec(options.commands, context, sys.stdout, sys.stderr)
        return application.run_shell(context, sys.stderr)
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        if context is not None:
            try: context.session.close()
            except Exception: pass
        return 2
    except ProjectLoadError as exc:
        print(f'error: {exc}', file=sys.stderr)
        lines = (_diagnostic_lines(exc.diagnostics, prefix="") if options.verbose
                 else _diagnostic_summary(exc.diagnostics, successful=False))
        for line in lines: print(line, file=sys.stderr)
        return 1
    except Exception as exc:
        print(f'error: {type(exc).__name__}: {exc}', file=sys.stderr)
        if context is not None:
            try: context.session.close()
            except Exception as cleanup:
                print(f'cleanup error: {type(cleanup).__name__}: {cleanup}', file=sys.stderr)
        return 1


def run_shell(options: ShellOptions) -> int:
    return _run_live(options, False)


def run_exec(options: ExecOptions) -> int:
    return _run_live(options, True)


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
        return run_resolve(ResolveOptions(tuple(options.out or ()), options.target,
            tuple(options.maps) if options.maps is not None else None, options.project,
            options.verbose))
    mode = StepMode.SOURCE if options.mode in ('c', 'source') else StepMode.ASSEMBLY
    common = dict(outputs=tuple(options.out or ()), socket=options.socket,
        maps=tuple(options.maps) if options.maps is not None else None,
        cdbs=tuple(options.cdbs) if options.cdbs is not None else None,
        source_roots=tuple(options.source_root), struct_headers=tuple(options.struct_header),
        signature=options.verify_signature, mode=mode, project=options.project,
        verbose=options.verbose)
    if options.command == 'shell':
        return run_shell(ShellOptions(**common))
    if options.command == 'exec':
        return run_exec(ExecOptions(commands=tuple(options.commands),
            timeout_seconds=options.timeout, **common))
    parser.error('a command is required')


if __name__ == '__main__':
    raise SystemExit(main())
