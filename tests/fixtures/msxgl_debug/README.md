# MSXgl debugger integration fixture

This directory contains a deterministic 32 KiB MSX1 ROM and its real SDCC
4.6.0 debug artifacts. They were generated with the build tool bundled in
MSXgl 1.5.0. The tiny program deliberately contains nested functions, a local
variable, globals, executable source lines, and a stable final loop.

Committed artifacts:

- `out/debug_fixture.rom`: executable ROM for openMSX;
- `out/debug_fixture.cdb`: SDCC declarations, scopes, lines, and links;
- `out/debug_fixture.map`: linked areas and absolute symbols;
- `out/debug_fixture.lst`: assembler/source listing.

Rebuild with the original distribution archive:

```sh
python3 tests/fixtures/msxgl_debug/rebuild.py /path/to/MSXgl-1.5.0.tar.gz
```

The fixture source is part of msxdbg. MSXgl is authored by Guillaume
“Aoineko” Blanchard and distributed under CC BY-SA 4.0. SDCC and the bundled
build tools retain their respective upstream licenses. Generated files are
kept solely to make parsing and debugger integration tests reproducible.
