# Benchmarks

The runner emits machine-readable JSON with median, p95, and maximum wall time
in milliseconds. Use a real, unchanged SDCC output tree and record the machine,
Python, openMSX, and SDCC versions beside each captured baseline.

Offline project loading:

```sh
python -m benchmarks.benchmark --out /path/to/project/out --iterations 20
```

Attach and 256-byte memory reads against an operator-prepared openMSX:

```sh
python -m benchmarks.benchmark --out /path/to/project/out \
  --socket /tmp/openmsx-USER/socket.PID --iterations 20
```

Instruction stepping mutates execution state and therefore requires the literal
`--allow-step` flag. Each iteration accepts one step; use it only on a disposable
or reproducible emulator session. The runner never starts openMSX, changes
media, resets, loads state, or changes speed.

A release baseline is valid only when all metadata and raw JSON are retained.
Regressions should be investigated when median or p95 exceeds the preceding
same-machine baseline by 25%; this is a review threshold, not a universal
performance promise.

The first qualified real-project sample is stored in
`baseline-msxciv-openmsx21.json`. It intentionally records one iteration: a
complete msxciv project load takes about 19 seconds on the reference machine.
Future same-machine captures should increase the iteration count when the
execution environment permits it.
