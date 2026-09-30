# msxdbg

`msxdbg` is an attach-only source debugger for SDCC-built MSX programs running
in openMSX. It resolves debug information offline and can attach to an emulator
that the operator has already started and prepared. It never starts openMSX,
changes media, resets the machine, loads a state, or changes emulator speed.

## Installation

Python 3.10 or newer is required. From a source checkout:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
msxdbg --version
```

For development and tests, use `python -m pip install -e '.[dev]'`.

## Quick start

Resolve an address without an emulator:

```sh
msxdbg resolve --out /path/to/sdcc/out 0x0100
```

Attach an interactive debugger to an already-running openMSX:

```sh
msxdbg shell --out /path/to/sdcc/out --socket /tmp/openmsx-USER/socket.PID
```

Run read-only commands as JSON Lines:

```sh
msxdbg exec --out /path/to/sdcc/out --socket /tmp/openmsx-USER/socket.PID \
  --json -c where -c 'info registers'
```

Use `--verify-signature 0xADDR=HEXBYTES` when firmware or a loader can stop
before the intended program is resident. Full command syntax is in
[COMMANDS.md](COMMANDS.md).

## Safety model

- The default workflow attaches to an existing emulator.
- Mutations are explicit and require a stopped target.
- `reset` and `load` require interactive, single-use confirmation and are not
  available to batch automation.
- A transport timeout after a mutation is reported as an unknown outcome and
  is never retried automatically.
- Live tests are disabled unless the operator supplies explicit environment
  variables; see [tests/integration/README.md](tests/integration/README.md).

## Troubleshooting

**No socket found:** pass the exact socket with `--socket`. Confirm that the
openMSX instance is running and that the current user can access the socket.

**Address is ambiguous:** qualify it with an image (`image::0xADDR`) or use a
project manifest with explicit image mappings. msxdbg does not silently choose
the first candidate.

**Source is unavailable:** add `--source-root`, or record the source root in a
project manifest. Paths embedded by the compiler may differ from the current
checkout.

**Signature remains pending:** verify the address and bytes against the exact
binary loaded in openMSX. Until matched, C-level interpretation is deliberately
restricted.

**Unsupported openMSX feature:** capability probing is read-only. The debugger
falls back where possible and otherwise reports the missing capability.

Compatibility boundaries are documented in [COMPATIBILITY.md](COMPATIBILITY.md).
The JSON stability contract is in [JSON_COMPATIBILITY.md](JSON_COMPATIBILITY.md).

