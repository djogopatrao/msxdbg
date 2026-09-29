# FX-CPU — synthetic Z80 frame fixture

`frame_walk.json` is a deliberately small, hand-reviewed oracle for Phase 4.
Addresses and stack words are decimal in JSON; instruction bytes are hexadecimal.

The SDCC frame prologue is exactly `push ix; ld ix,#0; add ix,sp`. Stack words
are little-endian: `[IX]` is the caller IX and `[IX+2]` is the return address.
The displayed caller PC is the return address, while scope lookup uses return
address minus one.

The fixture includes a three-frame chain, an IX cycle, an unknown caller and an
invalid return address. Tests construct the 64 KiB memory image from these words
so their expectations do not depend on the frame-walking implementation.
