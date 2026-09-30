# msxdbg — Specification for a Rewrite

2026-09-25 · written against v1.2c0 (commit 2de3c89)

**Development addendum:** [BACKLOG.md](BACKLOG.md) consolidates proposed features from sections 7–8 and COMMANDS.md section 12, with requirement IDs, acceptance criteria, dependencies, and exclusions. User-requested extensions F17/F18 add calculator-style print with hex()/bin() and object/function-like macro expansion; their updated semantics are documented in COMMANDS.md and BACKLOG.md. This specification remains the historical baseline; backlog entries do not imply implemented commands or relax the attach-only safety rules.

## 1. Purpose and scope

msxdbg is a gdb-style, source-level debugger for Z80 programs built with SDCC and the ASxxxx/SDLD linker, running under the openMSX emulator. It exists because SDCC's Z80 target emits nothing openMSX understands as debug info, so nothing maps a live PC back to a `.c` line. This spec describes the current tool (v1.2c0, commit 2de3c89, about 4,000 lines of Python) completely enough to rebuild it cleanly.

**Primary user:** one developer (and Claude Code agents acting for them) debugging msxciv, a mapper-heavy MSX2 MSX-DOS program split into a resident `.com` image plus a separately linked page-2 "DLL". Nothing in the design may be msxciv-specific; msxciv is the reference workload.

**What it must do**

- Resolve, offline and with no emulator: address to `module / file:line / function+offset`, and `file:line` or symbol to address.
- Attach to an already running openMSX over its control socket and provide breakpoints, stepping (source-line and instruction), run-to, disassembly, registers, memory and typed variable printing.
- Print C-level values: globals from `.map`, statics/locals/parameters from `.cdb` (when built with `--debug`), and C structs parsed from the project's own headers.
- Walk the call stack through SDCC's IX frame chain.
- Report page-3 RAM usage (static data, heap, free, stack, DOS reserve).

**Hard safety rules (carry over unchanged)**

- Never launch openMSX, boot a disk, insert media or change emulator speed. Attach only.
- `reset` and `load` (restore savestate) require the literal confirmation `reset yes` / `load yes`, typed by a human every time, and are never repeated by empty-line repeat or called by any automated flow.

**Out of scope:** VRAM debugging, BASIC, emulator lifecycle, mapper-segment-aware breakpoints (see open questions in section 8).

## 2. Architecture

The tool is a Python 3.9+ package (`msxdbg`, deps `prompt_toolkit` and `rich`) with two CLI subcommands over a layered core: file parsers feed a project model; a transport client feeds CPU helpers; the shell ties both together.

| Module | Lines | Role |
| --- | --- | --- |
| `__main__.py` | 128 | argparse CLI: `resolve` and `shell` subcommands |
| `openmsx_client.py` | 98 | Socket transport, one connection per Tcl command |
| `mapparse.py` | 103 | SDLD `.map` public-symbol table |
| `lstparse.py` | 184 | Per-module `.lst`: address to C-line, labels, `.globl`s |
| `cdbparse.py` | 521 | SDCC `.cdb`: functions, symbols, scopes, line records |
| `structparse.py` | 231 | C struct layouts from `.h` headers |
| `project.py` | 444 | `Project` (one linked image) and `CompositeProject` (several) |
| `cpu.py` | 562 | Registers, memory reads, disassembly, IX-frame detection, value formatting, page/slot info |
| `breakpoints.py` | 94 | Local breakpoint numbering over openMSX ids |
| `shell.py` | 1,866 | Interactive REPL: every command, expression evaluator, stop reporting, call-stack walk |

### 2.1 CLI

```
msxdbg resolve --out DIR [--out DIR ...] [--map FILE ...] <0xADDR | file.c:line>
msxdbg shell   --out DIR [--out DIR ...] [--map FILE ...] [--cdb FILE ...]
               [--socket PATH] [--source-root DIR] [--verify-signature ADDR=HEXBYTES]
               [--mode c|asm] [--struct-header FILE ...]
msxdbg --version
```

- `--out` (required, repeatable): one per independently linked binary. Each dir auto-discovers `*.lst`, `*.map`, `*.cdb`.
- `--map` / `--cdb` override discovery, but the same explicit list is applied to every `--out` image (a known wart).
- `resolve` needs no emulator. It prints `0xADDR  module (+0xOFFS)  file:line: text`, or `unresolved: <target>` on stderr with exit 1. A target containing `:` and not starting `0x` is `file:line`.
- `--verify-signature 0x0100=C31101`: a stop is only trusted once these bytes are seen at that address (see section 5).
- `--struct-header`: parse struct layouts from these headers; per-struct failures print `warning: struct 'X' not available in print: <reason>` and are skipped.

### 2.2 openMSX transport

- Socket: `/tmp/openmsx-*/socket.*`; default is the newest by mtime. Missing socket is a fatal error that says the tool never launches openMSX.
- Protocol per command: connect, read until `<openmsx-output>`, send `<command>TCL</command>`, read until `</reply>`, then check `result="ok"` vs `"nok"` and HTML-unescape the body. Timeout 5 s.
- One socket connection per command. Every round trip is expensive, so callers batch Tcl (e.g. all 16 registers in one `list [reg PC] [reg SP] ...`).
- Tcl source must avoid raw `<`, `>`, `&` (not escaped today; see section 7).
- `eval()` is a generic pass-through with no allowlist; the safety rules are enforced by callers.

**openMSX Tcl commands used:** `reg <name>`, `debug read memory <addr>`, `debug breaked`, `debug cont`, `debug break`, `step_in`, `step_over`, `step_out`, `run_to <addr>`, `disasm [addr [count]]`, `debug breakpoint create -address <addr>` / `remove <id>` / `list`, `get_selected_slot <page>`, `get_mapper_size <ps> <ss>`, `debug read {MapperIO|Main RAM regs} <page>`, `reset`, `savestate <name>`, `loadstate <name>`.

### 2.3 Data flow on a stop

1. Shell issues a run command (`continue`, `step`, ...) and polls `debug breaked`.
2. On stop: fetch registers in one round trip, then check the boot signature if configured.
3. Resolve PC through `CompositeProject.resolve` to module/file/line, and through `nearest_symbol` to `symbol+offset`.
4. Print the stop report (breakpoint number if PC matches one, source line or disassembled instruction depending on mode).
5. Reset the selected frame to 0 and invalidate per-stop caches.

## 3. Symbol and debug-info model

All source-level knowledge comes from four build artifacts: per-module `.lst` (address to C line), the linked `.map` (public symbol addresses), the optional linked `.cdb` (locals, scopes, statics; needs `--debug`), and project `.h` headers (struct layouts). Every parser is deliberately narrow and must fail per-item with a clear message, never guess.

### 3.1 `.map` (SDLD linker map)

- Scan for the table header `Value  Global`. Each row: `<8 hex addr>  <symbol>  [<module>]`.
- Rows with no module column are area-boundary pseudo-symbols (`s__DATA`, `s__HEAP`, `l__CODE`, ...). Keep them with module `""`; `info page3` depends on them.
- A line starting `ASxxxx Linker` means a new page header; stop consuming until the next `Value  Global`. Skip blank and `-----` lines.
- Only public (`.globl`) symbols appear. File-scope statics never do. C names carry a leading `_` (`_Map_GetTile`).
- Queries: `address_of(name)`, `nearest_symbol(addr)` (at or below, by bisect), `symbols_in_module`.
- Do NOT use nearest public symbol to decide module ownership of an address: measured 18% wrong on msxciv, because modules often start with static helpers.

### 3.2 `.lst` (per-module assembler listing)

- Fixed layout: each physical line is a 39-column head, one space, then text. The head right-aligns SDCC's own line number at column 39; the address is always `head[4:12]` (8 hex digits) when present.
- `;<path>:<line>: <text>` comment lines carry no address. They set a *pending* source line that attaches to the next address-bearing instruction.
- `.area NAME` switches the current area. Offsets are local per area and restart at 0 per module; re-entering an area continues its counter.
- `.globl NAME` collects the module's exported names; `.module NAME` sets the module name (default: file stem).
- A line whose text is only a label (`name:` or `name::`) records `labels[area][name] = offset`.
- A right-shifted absolute EQU or blank address consumes no space and is skipped. Opcode bytes are never parsed (they hold relocation placeholders like `CDr00r00`).
- Per area, keep parallel sorted arrays `(offset, SourceLine)`; the first instruction at an offset wins.
- `find_line(file_suffix, line)`: exact line, else the nearest *following* line in that file with code (gdb behaviour); returns the actual line so callers can say `note: X:N has no code -- using line M instead`.

Example (`civ_font.lst`):

```
                                   1817 ;./libs/civ_font.c:603: if ( fontId == FONT_ID_SMALL ...
    00000822 79               [ 4] 1818 	ld	a, c
```

### 3.3 Module base computation (`Project`)

1. For each module, for every `_CODE` label that is also `.globl`, look it up in each `.map`: `candidate = map_addr - local_offset`.
2. The module's `_CODE` base is the most common candidate; disagreeing candidates are kept in `base_conflicts` (never surfaced to the user today).
3. Build a sorted `(base, module)` table. `resolve(addr)` bisects it, then rejects the hit if `offset > last_known_offset + 16` (the address is in an unresolved gap).
4. `resolve_file_line` returns `base + offset` only for `_CODE`.

Measured 0 misattributions across every instruction address in msxciv. Only `_CODE` is resolved; `_HOME`, `_GSINIT`, `_GSFINAL` and data areas are not.

### 3.4 `.cdb` (SDCC debug records, linked)

Record grammar (derived from `sdcc/src/cdbFile.c`; full research in `sdcc_documentation/SDCC_ARGUMENT_LOCAL_ALLOCATION.md`):

```
M:<module>
F:<identity>({<size>}<typechain>),<tail>,<isISR>,<intNo>,<regBank>   function
S:<identity>({<size>}<typechain>),<tail>                             symbol
T:F<module>$<tag>[...]                                                struct (ignored)
L:<identity>:<hexaddr>                                                address (linked only)

<identity> = <scope>$<name>$<level>_<sublevel>$<block>
<scope>    = L<module>.<function>  (param/local) | F<module> (file static) | G (extern)
<tail>     = R,0,0,[<regs>]                       register-resident, low byte first
           | R,0,0,[<regs>],<storage>,<onStack>,<offset>
           | <storage>,<onStack>,<offset>
```

- Storage letters: `B` stack (IX/SP-relative), `E` fixed address (global or static), `C` code, `D` compiler statics, `F` far data (unused).
- Offsets are canonical "as if IX had been pushed": with a frame, address = `IX + offset`; without one, `SP + offset - 2` (valid only while SP equals its entry value).
- `L:` records are disambiguated by cross-referencing parsed F:/S: records, never by shape alone:
    - `C$<file>$<line>$<level>_<sub>$<block>` is a C-line record.
    - `G$fn$0$0` / `F<module>$fn$0$0` is a function entry; `XG$` / `XF<module>$` is its exit (address of the final `ret`, inclusive). Static functions use the `F`/`XF` forms.
    - `A$...` is ignored; an identity matching an S: record is that symbol's address.
- Exit markers are often absent (functions that clean up their own args end in `jp (hl)`). A function then extends to the next function's entry.
- Type chain: leading `D` means pointer/array (`DA` array, `DG`/`DC`/`DD`/`DF` pointers); trailing `:S` means signed. `sloc<N>` names are allocator temporaries and are hidden.

**Derived tables**

- `function_at(addr)`: bisect over entries, bounded by exit when known.
- `line_at(addr)`: nearest C-line record at or before addr within that function.
- Block ranges: per function, `block -> [min_addr, max_addr]` over its line records.
- **Parameter vs local:** a symbol whose block has *no* line records is a parameter (the implicit parameter-list scope is never executed). This is exact, not a heuristic.
- `in_scope_locals(addr)`: all parameters, plus locals whose block range contains addr. Empty if addr precedes the function's first line record.
- `find_symbol_by_name(name, pc)`: prefer a symbol of the function containing pc, then a global or file static, then the first match.

### 3.5 Struct headers (`structparse`)

- Strip comments; concatenate all `--struct-header` files; no `#include` following.
- Collect `#define NAME <int expr>` iteratively; array sizes may use known macros and `+ - * << ( )`, integer suffixes stripped, evaluated in a builtins-free sandbox.
- Recognise only `typedef struct [tag] { ... } Name;` with fields `type a, b[N];`.
- Primitive sizes: `bool i8 u8 c8 char` = 1; `i16 u16 c16 ptr short int unsigned` = 2; `i32 u32 f32 long` = 4; `i64 u64` = 8. No padding (SDCC Z80 packs to 1 byte).
- Rejected, per struct with a reason: bitfields, pointer declarators, inline nested struct/union, unknown types, unresolved array macros, and any struct embedding a rejected struct (fixed-point propagation).

### 3.6 Multi-image projects (`CompositeProject`)

One `Project` per `--out` directory, because the same module (e.g. `civ_font.c`) can be linked into both the resident image and a DLL at different addresses. Every query tries images in the order given and returns the first hit. `nearest_symbol` returns the smallest offset across images. `is_parameter_scope` is routed to the image whose `.cdb` owns the symbol identity. An address valid in two images is ambiguous; first match wins (mapper segment is not consulted).

## 4. Command reference (interactive shell)

The shell has 25 commands plus aliases, a `(msxdbg)` prompt, in-memory history, Tab completion and gdb-style empty-line repeat. Any exception in a handler is printed (`openMSX error: ...` or `error: ...`) and the shell keeps running.

| Command (aliases) | Syntax | Behaviour |
| --- | --- | --- |
| `break` (`b`) | `break <addr\|symbol\|file:line>` | Resolve target (section 5.1), create openMSX bp, print `Breakpoint N at 0xADDR: file:line \| text` |
| `delete` (`d`) | `delete <n>` | Remove from openMSX first, then locally; on openMSX failure keep it tracked and say so |
| `suspend` (`disable`) | `suspend <n>` | Remove from openMSX, keep number and location, mark suspended (idempotent) |
| `resume` (`enable`) | `resume <n>` | Recreate at same address under same number (idempotent) |
| `continue` (`c`) | `continue` | `debug cont`, then wait for stop |
| `step` (`s`) | `step` | Mode c: step into until the C line changes. Mode asm: one `step_in` |
| `next` (`n`) | `next` | As `step` but with `step_over` |
| `stepi` (`si`) | `stepi` | One `step_in`; always reports in asm style |
| `finish` | `finish` | `step_out`, then report (does not poll) |
| `until` (`advance`) | `until <target>` | `run_to <addr>`, then wait for stop |
| `where` | `where` | Re-print the stop report for the current PC |
| `backtrace` (`bt`) | `backtrace` | Walk IX chain; needs `.cdb` (section 5.5) |
| `frame` | `frame [n]` | Select frame n (or show selected) |
| `list` (`l`) | `list [[file:]line \| next \| previous]` | Show 11 source lines around target (default: PC); `>` marks PC line |
| `disassemble` (`disas`) | `disas [addr] [count] \| next \| previous` | 10 instructions by default from PC; numeric addr only |
| `print` (`p`, `?`) | `print <expr> [type]` | Section 6 |
| `info` | `info registers\|breakpoints\|pages\|symbol <expr>\|page3\|locals\|args` | Tables, see below |
| `mode` | `mode [c\|source\|asm\|assembly]` | Show or set step/report granularity |
| `reset` | `reset yes` | Soft reset via openMSX `reset`; bare `reset` only explains |
| `save` | `save` | `savestate msxdbg_<pid>`; takes no argument |
| `load` | `load yes` | `loadstate msxdbg_<pid>`; "not found" becomes `run 'save' first` |
| `clear` | `clear` | Hard clear: `ESC[H ESC[2J ESC[3J` (screen and scrollback); Ctrl-L does the same |
| `help` | `help` | Static help text |
| `quit` (`q`, `exit`) | `quit` | Leave the shell (EOF also exits; Ctrl-C at prompt is ignored) |

### 4.1 `info` subcommands

- `registers` (`reg`, `regs`): table Reg / Hex / Dec for `PC SP AF BC DE HL IX IY AF2 BC2 DE2 HL2 I R IM IFF`.
- `breakpoints` (`break`, `b`): Num / Address / Location / Status (`active` or `suspended`), or `No breakpoints.`
- `pages` (`page`, `slots`, `segments`): per CPU page 0-3, address range, slot `P` or `P.S`, and mapper segment. Uses `get_selected_slot`, `get_mapper_size`, then reads `MapperIO` or `Main RAM regs` debuggable.
- `symbol <expr>` (`sym`): `0xADDR is name+0xOFF (module M)` via nearest public symbol.
- `page3` (`free`): regions of 0xC000-0xFFFF: static (`max(s__DATA, 0xC000)` to `s__HEAP`), heap used (`s__HEAP` to word at `_g_HeapStartAddress`, else 0), free (heap top to SP), stack (SP to TPA top, the word at 0x0006), reserved (TPA top to 0x10000). Prints `free: N bytes`, or a bold corruption warning when heap top is at or above SP.
- `locals` (`local`) / `args` (`arguments`): section 6.4.

### 4.2 Interaction rules

- **Empty line** repeats the last command, except `reset` and `load` are never recorded (so Enter can't chain them).
- **Tab completion:** first word completes command names. `break`/`until`/`advance` complete known source files (shown without `./`, with a trailing `:`) and all `.map` symbols. `print`/`p`/`?` and `info symbol` complete the last symbol or register token of the expression (split on `+ - * / [ ( )`); `print`'s second word completes primitive types and loaded struct names. `info` completes its subcommands.
- **Output styling:** rich markup; errors red, warnings yellow, notes dim. Symbol names are escaped before markup.
- **Source files for `list` and stop reports** are found by: absolute path; else `--source-root/<path>`; else `<parent of each .lst's dir>/<path>` (i.e. the project dir above `out/`).

### 4.3 `resolve` subcommand output

```
$ msxdbg resolve --out projects/msxciv_tilesdll/out civ_font.c:603
0x9975  civ_font (+0x0822)  ./libs/civ_font.c:603: if ( fontId == FONT_ID_SMALL ...
```

## 5. Execution control semantics

### 5.1 Target resolution (`break`, `until`)

1. Contains `:` and doesn't start with `0x`: `file:line`, file matched by suffix. If the line has no code, fall forward to the next line with code and print a yellow note.
2. Decimal or `0x` hex: raw address. It may resolve to no source line (BIOS, unmapped); that is still a valid target.
3. Otherwise: exact `.map` symbol name (with the leading underscore).

Resolution happens once and the resulting location is stored on the breakpoint, so display never re-derives it.

### 5.2 Breakpoints

- openMSX returns its own id (e.g. `bp#3`); msxdbg keeps local numbers 1, 2, 3, ... never reused in a session.
- openMSX has no disable, so suspend = remove and remember; resume = recreate.
- Always remove on the openMSX side first, then drop local bookkeeping.
- Breakpoints are plain Z80-bus address matches, not qualified by slot or segment.

### 5.3 Waiting for and reporting a stop

**`wait_for_stop(timeout=None)`:** poll `debug breaked` every 50 ms. Ctrl-C sends `debug break` and prints `interrupted`. If a timeout is given and expires, send `debug break` and say so (no caller passes one today). Always ends with a stop report.

**Boot signature guard:** with `--verify-signature ADDR=BYTES`, each stop reads the bytes until they match once; after that the guard is off for the session. Until then, the report is only `stopped at 0xPC -- boot signature not yet seen, likely pre-load (BIOS/DOS); continue`. For msxciv the signature is `0x0100=C31101` (the `.com`'s `JP` to crt0).

**Stop report:**

1. Reset selected frame to 0.
2. Prefix `Breakpoint N,` when PC equals an active breakpoint's address.
3. PC unresolved: `stopped at 0xPC (unresolved -- outside any known module's _CODE)` plus 4 disassembled lines.
4. Resolved: `<module> <file>:<line>`, then mode c shows 3 source lines each side with the PC line marked (or just the `.lst` text plus a `--source-root` hint); mode asm shows the line text plus 4 disassembled lines.

**Disassembly line format** (shared by `disassemble`, `stepi` and asm-mode reports): `=>` marker on PC, address, instruction padded to 24, `; file:line` when resolvable, and `<symbol+0xOFF>` for the first 16-bit immediate (`#XXXX`, exactly four hex digits) that resolves to a nearest public symbol.

openMSX `disasm` output is parsed by fixed columns: address in 0-3, instruction text in 6-25, raw bytes from 26. Splitting on whitespace runs is wrong (wide operands leave one space).

### 5.4 Stepping

- **Source-line step (mode c `step`/`next`):** record the start location; loop `step_in` (or `step_over`), re-reading PC and resolving it each time. Stop when: the location becomes unresolved; the (file, line) differs from the start; PC hits an active breakpoint; or 20,000 instructions pass (then warn). Ctrl-C breaks the loop. Each iteration costs 2 or more socket round trips.
- **Instruction step:** one `step_in` / `step_over`; `stepi` always reports asm style.
- **finish:** openMSX `step_out`, reported immediately without polling.
- **until:** `run_to <addr>` then `wait_for_stop`.
- **disassemble previous:** Z80 instructions vary in length, so back up `count * 3` bytes, disassemble forward, keep the last `count` instructions that end before the old start.

### 5.5 Call-stack walk (`backtrace`, `frame`)

SDCC's IX prologue is exactly `push ix; ld ix,#0; add ix,sp`. That leaves `[IX]` = caller's IX and `[IX+2]` = return address, a classic frame-pointer chain.

1. Frame 0 = live PC; function from `.cdb`. It has a frame if the function has the IX prologue (checked by disassembling 3 instructions at entry, memoized per function name) and no `pop ix` has executed between entry and PC (disassemble entry..PC by static address order).
2. If frame 0 has no IX frame, the walk ends there.
3. Otherwise repeat up to 64 frames: read old IX and return address; resolve the caller as the function containing `return_addr - 1`. Unknown function: append a `?? ()` frame and stop. Caller without its own IX frame: append it (locals unavailable) and stop. An IX value already seen: stop (loop guard).

Output is gdb-flavoured: `*#N  0xADDR in fn () at file:line`, `*` on the selected frame, with a dim note explaining where and why the walk stopped. `frame n` selects a frame for `print` and `info locals/args`; the selection resets to 0 on every stop.

In a selected caller frame: stack locals are read at `frame.ix + offset`; register-resident locals are refused (a suspended caller's registers leave no trace); frames without IX are refused. Scope lookups use `frame.pc - 1` so the return address maps into the call instruction's line.

## 6. Expressions and value printing (legacy baseline)

**Rewrite override:** this section describes v1.2c0. Requirements F17/F18 in §8.7 replace implicit memory reads for untyped arithmetic with calculator results, add hex()/bin() and macro expansion, and make untyped parentheses grouping. See COMMANDS.md §8 for the current proposed contract.

`print <expr> [type]` splits its argument on whitespace: the first token is the target, the second (if any) the type. Registers are fetched once per command.

### 6.1 Expression grammar

```
target   := '[' expr ']' | '(' expr ')'     -- whole target wrapped: read memory at expr
          | ident '[' expr ']'               -- array element: sym + index*sizeof(type)
          | expr
expr     := term (('+'|'-') term)*
term     := factor (('*'|'/') factor)*
factor   := ('+'|'-') factor | '(' expr ')' | atom
atom     := register | number | map_symbol
number   := '#'hex | '0x'hex | decimal
```

- Tokens: `#hex`, `0xhex`, decimal, identifiers, `+ - * / ( )`; any other character fails the whole expression.
- Division truncates toward zero (C semantics); division by zero fails. The result is masked to 16 bits.
- Atom lookup order: register (16-bit pairs and 8-bit halves, any case), then number, then `.map` symbol.
- Registers: `PC SP AF BC DE HL IX IY AF2 BC2 DE2 HL2 I R IM IFF` plus halves `A F B C D E H L`, shadows `A2..L2`, `IXH IXL IYH IYL PCH PCL SPH SPL` (derived locally from the pairs).

### 6.2 Resolution order for `print`

1. Not indirect and the target is a register name: if `.cdb` has a symbol with that name (scoped to the selected frame's PC), print the variable; otherwise print the register as `NAME = dec (0xhex)` (4 hex digits for pairs, 2 for halves). A type is ignored with a warning.
2. `ident[expr]`: base from `.map` only; a type is mandatory (primitive or struct) to compute element size.
3. Otherwise evaluate the expression to an address.
4. If evaluation fails and the target is a plain identifier: try `.cdb` (local/param of the selected frame, then static/global).
5. Still unresolved: `could not evaluate: X`, plus, if the name is a label in some `.lst` without a `.map` entry, a note that it is probably a C `static`, with module, area and offset.

A plain (non-indirect) numeric expression like `print 0xC000 u16` reads memory at that address. `print _sym` reads memory at the symbol's address as `u8` by default. There is no "print the value of the expression itself" form except via registers.

### 6.3 Types and formatting

| Type (aliases) | Bytes | Output |
| --- | --- | --- |
| `u8` (`b`), default | 1 | `200 (0xc8)` |
| `i8` (`s8`) | 1 | `-56 (0xc8)` |
| `u16` (`word`) | 2 | `515 (0x0203)` little-endian |
| `i16` (`s16`) | 2 | signed, hex of raw |
| `u32` (`dword`), `i32` (`s32`) | 4 | dec plus 8-digit hex |
| `u64`, `i64` (`s64`) | 8 | dec plus 16-digit hex |
| `f32` (`float`) | 4 | IEEE-754 little-endian |
| `bool` | 1 | `true (0x01)` |
| `char` (`c`), `c8` | 1 | `'A' (65 / 0x41)`, non-printables as `\xNN` |
| `c16` | 2 | numeric |
| `ptr` | 2 | `0x1234` |
| `str` (`cstr`) | up to 256 | `"text"` latin-1 to NUL, notes truncation |
| struct name | computed | multi-line block (below) |

**Struct printing:** one memory read of the whole struct, then per field: scalars via the table above (raw C types mapped: `int`=i16, `unsigned`=u16, `long`=i32, ...); nested struct as an indented block; arrays show up to 16 elements then `... N more`. Output: `name = 0xADDR: Name {` ... `}`.

**Note:** SDCC's `float` is not IEEE-754 on every target; `f32` assumes it is (unverified for Z80).

### 6.4 Printing `.cdb` symbols

| Storage | Location | Label shown |
| --- | --- | --- |
| `E` (global/static) | linked `L:` address | `0xADDR` |
| `B`, IX frame active | `IX + offset` | `0xADDR (ix-relative)` |
| `B`, no frame | `SP + offset - 2` | `0xADDR (sp-relative)` |
| `B`, caller frame | `frame.ix + offset` | `0xADDR (ix, frame N)` |
| register list | bytes from registers, low first | `(register L,H)` plus dim caveat |
| none of the above | - | `has no resolvable location here -- likely optimized out` |

- Default type when none is given: from size and sign (`u8 i8 u16 i16 u32 i32`). Pointers, arrays and structs (type chain starting `D`) have no default: the user must give a type, and the tool says so instead of truncating.
- Register-resident values carry the caveat "only reliable right at its defining source line": `.cdb` has no live ranges, so the register may already be reused.
- Struct types are refused for register-resident symbols.

**`info locals` / `info args`:** needs `.cdb`. Uses the selected frame's PC. Table title `<fn> -- locals|parameters [(frame N)]`, columns Name / Location / Value. Register rows get `*` and a single footnote. Values: scalar default format; plain pointers (type `D` but not `DA`, size 2) as `u16`; everything else as raw hex bytes in memory order. Missing data shows `optimized out`, or a specific reason in caller frames. `none` when the list is empty; a message when PC is outside every known function.

## 7. Known issues and quirks in v1.2c0

These are the defects and limits the rewrite should fix or consciously keep. "Confirmed" means reproduced in this review (all 344 existing tests pass on 2026-09-25); "From code" means read from source but not run.

### 7.1 Bugs

| # | Issue | Status | Effect |
| --- | --- | --- | --- |
| B1 | `_split_indirect` strips outer brackets whenever the target starts with `(` and ends with `)` | Confirmed | `print (hl+3)*(hl)` becomes a memory read of the malformed `hl+3)*(hl` |
| B2 | `print` splits on whitespace | From code | `print hl + 3` treats `+` as the type; `info symbol` only reads its first token |
| B3 | Breakpoints are not removed on `quit` | From code | They stay armed in openMSX after the debugger exits |
| B4 | `file:line` matching uses `endswith` with no path-boundary check | From code | `map.c:10` can match `worldmap.c`; the first module in dict order wins |
| B5 | `.cdb` functions are keyed by bare name | From code | Two `static` functions with the same name in different modules collide |
| B6 | Frame-prologue cache is keyed by function name across images | From code | Same-named functions in resident and DLL images share one cached answer |
| B7 | `finish` reports right after `step_out` without polling `debug breaked` | From code, not verified live | May report while the CPU is still running |
| B8 | `disassemble <symbol>` raises `ValueError` | From code | Only numeric addresses work, with a generic `error:` message |
| B9 | Tab completion list lacks `backtrace`, `bt`, `advance`, `?` | Confirmed | Those commands don't complete |
| B10 | Tcl text is sent without XML escaping | From code | Safe today only because every command is built from integers and fixed names |
| B11 | Explicit `--map`/`--cdb` are applied to every `--out` image; only the first `.cdb` per image is used | From code | Wrong with multiple images plus overrides |

### 7.2 Design limits

- **Round-trip cost:** one socket connection per Tcl command. A C-line step does 2+ connections per instruction, up to 20,000 instructions. `ix_frame_active_at` disassembles the whole span from function entry to PC on every `print`/`info locals`.
- **Memory reads** loop `debug read memory` in Tcl (`read_block` was avoided because it returns binary). Strings always read 256 bytes.
- **Only `_CODE` is resolved.** Init code (`_GSINIT`, `_HOME`) shows as unresolved.
- **Statics without `.cdb`** can only be explained (module, area, offset), not read.
- **Register-resident values** are unreliable away from their defining line; `.cdb` has no live ranges.
- **Epilogue detection** is by static address order, so a function with several inline `pop ix` epilogues can misjudge frame state.
- **Last function in the link** has no upper bound when its exit marker is absent.
- **Mapper segments** are not part of breakpoints or address resolution; an address valid in two images resolves to the first.
- **Symbol names** must include SDCC's leading underscore for `.map` lookups (`break _Map_GetTile`), unlike `.cdb` names.
- **Boot signature** stops are reported but not auto-continued; msxciv boots produce roughly 35 s of spurious hits the user must `continue` through by hand.
- **Shell class is 1,866 lines** mixing parsing, evaluation, openMSX I/O and rendering; state such as `_list_state` and `_disas_state` are loose dicts.
- **Live paths are verified by hand only.** Tests use scripted fake clients and real SDCC fixture output; there is no integration test against a real openMSX.

### 7.3 Behaviours to keep

- Attach-only; `reset yes` / `load yes` confirmations; never repeat them on Enter.
- Module ownership from computed bases, never from nearest public symbol.
- Parameter detection by "block has no line records".
- Refuse rather than guess: no default type for pointers/arrays/structs, explicit reasons for unreadable caller-frame values, per-struct parse errors.
- Remove breakpoints on the openMSX side before dropping local state.

## 8. Design for the new version

Recommendation: keep Python and the same CLI and command vocabulary, so existing habits and the `openmsx-debug` / `msxdbg-bisect` skills keep working. Rebuild the inside as five layers with one-way dependencies, and add a non-interactive mode for agents.

### 8.1 Layers

| Layer | Owns | Must not know about |
| --- | --- | --- |
| `debuginfo` | Parsers for `.map`, `.lst`, `.cdb`, headers; one `Image` model per linked binary: modules, functions, line table, variables, types | openMSX, terminal |
| `target` | `Target` interface (registers, read/write memory, disasm, breakpoints, run/step/break, slots); `OpenMSXTarget` and `FakeTarget` | debug info |
| `session` | Stop state: registers, PC location, frame list, caches, all invalidated together on each stop; breakpoint table; safety gates | rendering |
| `eval` | Tokenizer, parser to an AST, typed evaluation against session and debug info | terminal |
| `ui` | Command registry, completion, rendering (rich tables or JSON) | Tcl |

### 8.2 Key changes

1. **One `Image` model.** Merge `.lst`, `.map` and `.cdb` into typed records keyed by `(image, module, name)`, fixing B5/B6. `.cdb` is the source of truth when present; `.lst`+`.map` is the fallback. Parse `.cdb` `T:` records for struct types when available; keep header parsing as a fallback.
2. **Accept C names.** `break Map_GetTile` should find `_Map_GetTile`.
3. **Real expression language.** Tokenize the whole argument (fixes B1/B2), expand supported macros, and parse to an AST. Use `print/u16 expr` as the preferred explicit memory type and retain an unambiguous trailing type. Untyped arithmetic computes a value; hex()/bin() select presentation; `[expr]` explicitly reads memory. Untyped parentheses group expressions. Typed C operators `*p`, `&x`, `a[i]`, `s.f`, `p->f` remain a subsequent increment. See §8.7 for the requested calculator/macro requirements; C casts are not selected for the initial grammar.
4. **Cheaper transport.** Verify whether one openMSX connection can carry many `<command>`s (the protocol looks stream-based); if so, keep one open. Read memory in one call, e.g. `binary encode hex [debug read_block memory A N]` (verify on the installed Tcl). XML-escape all Tcl (B10).
5. **Per-stop cache.** Registers, frame walk, and each function's frame state are computed at most once per stop. Find epilogues once per function (all `pop ix` addresses) instead of disassembling entry..PC on every print.
6. **Command registry.** Each command declares names, aliases, argument completer, help text, whether Enter may repeat it, and whether it needs a typed confirmation. Help and completion are generated from it (fixes B9).
7. **Clean exit.** Remove every breakpoint the session created on quit, EOF or crash (B3); say so.
8. **Correct `finish`.** Poll for the stop like `continue` (B7).
9. **Path-aware `file:line`.** Match on path-component boundaries; report ambiguity across modules or images instead of taking the first (B4).
10. **Agent mode.** `msxdbg exec --out ... -c 'break x.c:10' -c continue -c 'info locals' --json` runs commands non-interactively and emits one JSON object per command. Safety gates still apply: `reset`/`load` stay unavailable without an interactive typed confirmation.

### 8.3 New features worth adding

- `continue --until-signature`: auto-continue spurious pre-boot stops.
- Conditional breakpoints via openMSX `-condition`, including "only when mapper page N holds segment S".
- Watchpoints (`debug set_watchpoint`) on globals and statics.
- Resolve `_HOME` and `_GSINIT` code.
- Surface `base_conflicts` as a startup warning.

### 8.4 Test strategy

- Keep the fixture approach: real SDCC output (`.lst`, `.map`, `.cdb`, sources) checked in, each parser unit-tested.
- `FakeTarget` backed by a memory image and scripted PCs, so session and eval tests need no Tcl strings.
- Golden-output tests for every command in both rich and JSON renderings.
- An opt-in integration suite against a live openMSX with a small test ROM (never msxciv's disk; see section 1).

### 8.5 Suggested order of work

| Phase | Delivers | Done when |
| --- | --- | --- |
| 1 | `debuginfo` + `resolve` CLI | Byte-identical `resolve` output on the existing fixtures |
| 2 | `target` + `session` + breakpoints/run/step | Stop reports match v1.2c0 on scripted fakes |
| 3 | `eval` + macros + calculator + `print` + `info` | B1/B2 fixed; F17/F18 acceptance tests; preserved typed reads and explicit migration of untyped arithmetic/parentheses |
| 4 | `.cdb` locals, frames, backtrace | Current `TestInfoLocalsAndArgs` / `TestCallStackWalk` scenarios pass |
| 5 | Agent mode, new features | JSON contract documented |

### 8.6 Open questions

- Does openMSX keep a control connection open across commands? (decides transport design)
- Does SDCC's Z80 `float` use IEEE-754 layout? (decides `f32`)
- Resolved: prefer `/type` and retain an unambiguous trailing type; untyped calculator semantics follow §8.7.
- Pending: external configuration of macro source files, include paths and compilation flags; unsupported or unknown preprocessing context must not be guessed.


### 8.7 Requested additions: calculator and macros (F17/F18)

These requirements describe the rewrite and override the legacy print semantics in §6 where they differ.

- `print 2 + 3 * 4` computes 14 without reading memory; `print (2 + 3) * 4` computes 20. Integer results are not masked to 16 bits. Division truncates toward zero.
- `print hex(255)` displays `0xff`; `print bin(10)` displays `0b1010`. These are built-in integer presentation functions, not calls into the debugged program. Their integer values remain usable in nested arithmetic; only an outermost call selects output base. JSON retains the numeric value and display base.
- `[expr]` explicitly reads memory. Preserve typed reads such as `print 0xC000 u16`, `print/u16 hl + 3`, and isolated MAP/CDB variable inspection. `print (hl)` now computes HL; migrate the untyped legacy indirect form to `print [hl]`.
- Expand object-like and function-like macros before AST parsing. Accept `print [0x8000+MY_OFFSET] u16` and `print NLV( _g_teste,_g_outro_teste)` when their definitions and required operators are available. NLV has no built-in meaning.
- Record definition tokens and provenance per image/compilation context. Use explicitly loaded sources/headers, including supplied struct headers. Reject unresolved preprocessing conditions, ambiguous definitions, recursion, invalid arity and unsupported constructs rather than inventing an expansion.
- The first increment supports a demonstrated subset of object/function macros, continuation lines and nested arguments; full C preprocessing, stringification, token pasting and variadic macros are not promised. Reserve hex/bin names and diagnose macro conflicts.
- Constant-only expressions need no target reads or valid stop. Live registers/variables/memory require inspection context; macros never execute arbitrary host/target functions or writes.

Detailed acceptance criteria and dependencies are in BACKLOG F17/F18; module contracts are in MODULE_DESIGN §§6 and 13. No implementation is implied by this specification update.
