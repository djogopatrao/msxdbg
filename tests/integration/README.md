# openMSX live integration

This suite is opt-in and attaches only to an openMSX instance prepared and
paused by the operator. It never launches openMSX, inserts media, resets the
machine, loads a state, or changes emulator speed.

Read-only target validation:

```sh
MSXDBG_LIVE_SOCKET=/tmp/openmsx-USER/socket.PID \
python3 -m pytest -q tests/integration/test_openmsx_live.py
```

To also validate JSON batch mode, point `MSXDBG_LIVE_OUT` at the SDCC output
directory matching the program already loaded in the emulator:

```sh
MSXDBG_LIVE_SOCKET=/tmp/openmsx-USER/socket.PID \
MSXDBG_LIVE_OUT=/path/to/prepared/program/out \
python3 -m pytest -q tests/integration/test_openmsx_live.py
```

Large SDCC output directories can take longer to parse before the 10-second
batch deadline begins. The integration subprocess therefore allows up to two
minutes for project loading plus command execution.

The two mutating scenarios require separate, literal opt-ins:

```sh
MSXDBG_LIVE_SOCKET=/tmp/openmsx-USER/socket.PID \
MSXDBG_LIVE_BREAKPOINTS=1 \
python3 -m pytest -q tests/integration/test_openmsx_live.py

MSXDBG_LIVE_SOCKET=/tmp/openmsx-USER/socket.PID \
MSXDBG_LIVE_EXECUTION=1 \
python3 -m pytest -q tests/integration/test_openmsx_live.py
```

The breakpoint test removes only the breakpoint it created, including when
the assertion fails. The execution test performs exactly one `step_in`. Do not
enable either flag against an irreplaceable emulator session.

Persistent transport and binary block reads are read-only but transfer the
complete 64 KiB CPU address space. Enable their comparison separately:

```sh
MSXDBG_LIVE_SOCKET=/tmp/openmsx-USER/socket.PID \
MSXDBG_LIVE_OPTIMIZATIONS=1 \
python3 -m pytest -q tests/integration/test_openmsx_live.py
```

## Reproducible MSXgl ROM scenario

The repository includes `tests/fixtures/msxgl_debug/out/debug_fixture.rom`,
built by MSXgl 1.5.0 with SDCC 4.6.0. Load that ROM in openMSX and pause it
before address `0x4065` is reached. Then run the source-breakpoint scenario:

```sh
MSXDBG_LIVE_SOCKET=/tmp/openmsx-USER/socket.PID \
MSXDBG_LIVE_EXECUTION=1 \
MSXDBG_LIVE_MSXGL_FIXTURE=1 \
python3 -m pytest -q \
  tests/integration/test_openmsx_live.py::test_live_msxgl_source_breakpoint_stops_at_compiled_line
```

This test installs `break debug_fixture.c:17`, continues the prepared target,
verifies the matching local breakpoint and source location, and removes the
breakpoint during normal batch cleanup. It does not insert or reload the ROM.

The same fixture provides live regression scenarios for issues #3, #4, and #7:

```sh
MSXDBG_LIVE_SOCKET=/tmp/openmsx-USER/socket.PID \
MSXDBG_LIVE_EXECUTION=1 \
MSXDBG_LIVE_BREAKPOINTS=1 \
MSXDBG_LIVE_MSXGL_FIXTURE=1 \
python3 -m pytest -q tests/integration/test_openmsx_live.py \
  -k 'issue_3 or issue_4 or issue_7'
```

- Issue #3 stops at the compiled line, then checks both an explicitly requested
  non-executable source line and `list` at the current PC.
- Issue #4 creates a source breakpoint and verifies that `info breakpoints`
  preserves its file and line in the JSON contract.
- Issue #7 resumes the emulator outside the session, interrupts it externally,
  and verifies that `backtrace` reconciles the stopped target and snapshot.

These scenarios mutate execution or breakpoints only under the corresponding
explicit opt-in. Each test expects the MSXgl fixture ROM to be loaded and the
emulator to be paused when the suite starts.
