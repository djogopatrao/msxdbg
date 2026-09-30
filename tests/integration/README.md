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
