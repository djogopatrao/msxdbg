"""C03: the documented offline command, including multi-image failures."""
import subprocess
import sys

import pytest

from msxdbg.__main__ import main
from test_project_loading import write_module


def test_resolve_address_golden_without_network(tmp_path, capsys, monkeypatch):
    import socket
    write_module(tmp_path, 'main', 0x8000)
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('resolve opened a socket'))
    assert main(['resolve', '--out', str(tmp_path), '0x8004']) == 0
    result = capsys.readouterr()
    assert result.out == '0x8004  main (+0x0004)  src/main.c:11: source 11\n'
    assert 'project loaded with 2 warnings' in result.err
    assert 'use --verbose' in result.err


def test_resolve_line_advances_and_reports_effective_line(tmp_path, capsys):
    write_module(tmp_path, 'main', 0x8000)
    assert main(['resolve', '--out', str(tmp_path), 'main.c:9']) == 0
    result = capsys.readouterr()
    assert result.out.startswith('0x8000  main (+0x0000)')
    assert 'using line 10' in result.err


def test_resolve_missing_is_stderr_and_status_one(tmp_path, capsys):
    write_module(tmp_path, 'main', 0x8000)
    assert main(['resolve', '--out', str(tmp_path), 'missing.c:1']) == 1
    result = capsys.readouterr()
    assert result.out == ''
    assert 'unresolved: missing.c:1' in result.err


def test_multi_image_requires_qualification(tmp_path, capsys):
    for name in ('resident', 'overlay'):
        write_module(tmp_path / name, 'main', 0x8000)
    args = ['resolve', '--out', str(tmp_path / 'resident'), '--out', str(tmp_path / 'overlay')]
    assert main(args + ['0x8000']) == 1
    result = capsys.readouterr()
    assert result.out == '' and 'ambiguous:' in result.err
    assert 'resident::' in result.err and 'overlay::' in result.err
    assert main(args + ['overlay::main.c:10']) == 0
    assert capsys.readouterr().out.startswith('0x8000')


def test_ambiguous_map_overrides_fail_before_loading(tmp_path, capsys):
    assert main(['resolve', '--out', str(tmp_path / 'a'), '--out', str(tmp_path / 'b'),
                 '--map', str(tmp_path / 'missing.map'), '0x8000']) == 2
    assert '--map overrides require exactly one --out' in capsys.readouterr().err


@pytest.mark.parametrize('target', ['_symbol', '1234', '0x10000', 'main.c:0', 'main.c:-1', '::0x8000', '0x8000+1'])
def test_invalid_target_is_usage_failure_before_loading(tmp_path, target, capsys):
    assert main(['resolve', '--out', str(tmp_path / 'absent'), target]) == 2
    assert 'error:' in capsys.readouterr().err


def test_initialization_error_is_reported_without_traceback(tmp_path, capsys):
    assert main(['resolve', '--out', str(tmp_path / 'absent'), '0x8000']) == 1
    result = capsys.readouterr()
    assert result.out == '' and '1 project diagnostics' in result.err
    assert 'load.missing-directory' not in result.err

    assert main(['resolve', '--verbose', '--out', str(tmp_path / 'absent'),
                 '0x8000']) == 1
    assert 'load.missing-directory' in capsys.readouterr().err
    assert 'Traceback' not in result.err


def test_module_entrypoint_and_version_do_not_require_artifacts(tmp_path):
    result = subprocess.run([sys.executable, '-m', 'msxdbg', '--version'], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.startswith('msxdbg ')
    assert result.stderr == ''
    write_module(tmp_path, 'main', 0x8000)
    result = subprocess.run([sys.executable, '-m', 'msxdbg', 'resolve', '--out', str(tmp_path), '0x8000'],
                            capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.startswith('0x8000  main')


def test_repeated_out_is_usage_failure(tmp_path, capsys):
    assert main(['resolve', '--out', str(tmp_path), '--out', str(tmp_path), '0x8000']) == 2
    assert 'duplicate --out' in capsys.readouterr().err


def test_missing_arguments_use_argparse_status_two(capsys):
    with pytest.raises(SystemExit) as error:
        main(['resolve', '0x8000'])
    assert error.value.code == 2
    assert '--out' in capsys.readouterr().err
