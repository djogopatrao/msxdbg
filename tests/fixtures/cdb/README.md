# CDB parser fixtures

`scoped.cdb` is synthetic, based on SPEC.md §3.4 and the SDCC team's
[CDB File Format](https://sourceforge.net/p/sdcc/wiki/CDB%20File%20Format/).
It is not compiler-generated output. No SDCC executable is available in this
workspace. It includes links before declarations, an M record after declarations,
full Z80-style sublevels, register-plus-stack tails and a self-referencing type.

T support is intentionally limited to a single physical line containing
`Fmodule$tag[({offset}S:S$name$level$block({size}chain:sign),tail)...]`.
The tests demonstrate scalar members, pointer references, arrays and empty
member lists. The parser preserves encoded members; it does not infer sizes,
struct versus union, resolve reference graphs or certify a usable memory layout.
Bitfield members and unknown member type tokens are unsupported. Unsupported or
truncated T encodings produce localized diagnostics. F/S type chains remain
opaque (including unknown tokens) for the loader to resolve or reject.

Links remain separate from F/S declarations for cross-file reconciliation in the
loader. An X marker retains its inclusive address; no missing function entry,
exit, parameter classification or absolute variable address is synthesized.
