"""D08 contract tests for the SDCC listing parser."""

from pathlib import Path

from msxdbg.debuginfo.diagnostics import ParseResult
from msxdbg.debuginfo.lst_parser import ListingData, parse_lst


ORIGIN = Path("build/example.lst")


def instruction(offset: int, text: str = "nop") -> str:
    return f"{f'    {offset:08X} 00               [ 4]':<34}{1:5} {text}"


def test_empty_listing_uses_file_stem() -> None:
    result = parse_lst([], ORIGIN)
    assert isinstance(result, ParseResult)
    assert isinstance(result.value, ListingData)
    assert result.value.module_name == "example"
    assert result.value.lines == ()


def test_module_areas_exports_labels_and_source_association() -> None:
    result = parse_lst([
        '.module "demo"',
        ".area _CODE",
        ".globl _entry",
        instruction(0, "_entry:"),
        ";src/demo.c:42: return 0;",
        instruction(2),
    ], ORIGIN)
    data = result.value
    assert data.module_name == "demo"
    assert [area.name for area in data.areas] == ["_CODE"]
    assert [symbol.name for symbol in data.globals] == ["_entry"]
    assert [symbol.name for symbol in data.labels] == ["_entry"]
    assert data.find_line("demo.c", 42).offset == 2


def test_reentered_area_and_first_offset_wins() -> None:
    result = parse_lst([
        ".area _CODE", instruction(1), ".area _DATA", instruction(1),
        ".area _CODE", instruction(1),
    ], ORIGIN)
    assert [(line.area, line.offset) for line in result.value.lines] == [("_CODE", 1), ("_DATA", 1)]
    assert [item.code for item in result.diagnostics] == ["lst.duplicate-offset"]


def test_non_records_do_not_consume_pending_source() -> None:
    result = parse_lst([";src/demo.c:7: x++;", "    EQU value", instruction(3)], ORIGIN)
    assert result.value.lines[0].source.line == 7


def listing(text: str, offset: int | None = None, head: str | None = None) -> str:
    prefix = head if head is not None else (f"    {offset:08X} CDr00r00 [17]" if offset is not None else "")
    return f"{prefix:<34}{123:5} {text}"


def test_fixed_columns_and_relocation_bytes() -> None:
    result = parse_lst([
        listing('.module "fixed"'), listing('.area _HOME (REL,CON)'),
        listing('.globl _call'), listing('_call::', 0),
        listing(';C:\\src\\demo.c:23: call();'), listing('call _target', 0),
        listing('', 3),  # byte continuation is not another instruction
        listing('value = 0x1234', head='      00001234'),
        listing('value EQU 4', 4), listing('nop', 5),
    ], ORIGIN)
    data = result.value
    assert result.diagnostics == ()
    assert data.module_name == 'fixed'
    assert [(x.name, x.area, x.offset) for x in data.labels] == [('_call', '_HOME', 0)]
    assert [(x.name, x.area, x.offset) for x in data.globals] == [('_call', '_HOME', None)]
    assert [(x.area, x.offset) for x in data.lines] == [('_HOME', 0), ('_HOME', 5)]
    assert data.lines[0].source.normalized_path == 'C:/src/demo.c'
    assert data.lines[0].source.text == 'call();'
    assert data.lines[0].origin.line == 6
    assert data.lines[1].source is None


def test_pending_source_survives_labels_directives_equ_and_area_reentry() -> None:
    result = parse_lst([
        listing(';demo.c:10: old'), listing(';demo.c:11: current'),
        listing('.area _CODE'), listing('_start:', 9),
        listing('absolute EQU 2', head='      00000002'),
        listing('nop', 9), listing('.area _DATA'), listing('nop', 0),
        listing('.area _CODE'), listing(';demo.c:12: next'), listing('ret', 12),
    ], ORIGIN)
    assert result.diagnostics == ()
    assert [(x.area, x.offset) for x in result.value.lines] == [('_CODE', 9), ('_CODE', 12), ('_DATA', 0)]
    assert [x.source.line if x.source else None for x in result.value.lines] == [11, 12, None]
    assert [x.name for x in result.value.areas] == ['_CODE', '_DATA']


def test_duplicate_consumes_its_source_without_overwriting_first() -> None:
    result = parse_lst([
        listing(';demo.c:1: first'), listing('nop', 0),
        listing(';demo.c:2: duplicate'), listing('nop', 0), listing('ret', 1),
    ], ORIGIN)
    assert result.value.lines[0].source.line == 1
    assert result.value.lines[1].source is None
    assert [(d.code, d.origins[0].line) for d in result.diagnostics] == [('lst.duplicate-offset', 4)]


def test_labels_with_same_name_remain_in_their_area() -> None:
    result = parse_lst([listing('.area '+area) if i % 2 == 0 else listing('local:', i)
                        for i, area in enumerate(['_CODE', '', '_DATA', ''])], ORIGIN)
    assert [(x.name, x.area, x.offset) for x in result.value.labels] == [('local', '_CODE', 1), ('local', '_DATA', 3)]


def test_errors_are_localized_and_later_valid_records_survive() -> None:
    result = parse_lst([
        None, listing('.area'), listing('.globl'), listing('missing:'),
        listing('too_big:', 0x10000), listing('nop', 0x10000),
        '    0000', listing('nop', 0xFFFF),
    ], ORIGIN)
    assert [d.code for d in result.diagnostics] == [
        'lst.invalid-line', 'lst.empty-area', 'lst.empty-global',
        'lst.label-without-offset', 'lst.offset-out-of-range', 'lst.offset-out-of-range',
    ]
    assert [d.origins[0].line for d in result.diagnostics] == list(range(1, 7))
    assert [x.offset for x in result.value.lines] == [0xFFFF]


def test_long_line_generator_truncated_end_and_lookup() -> None:
    rows = [listing(';demo.c:7: '+ 'x'*10000), listing('nop', 3),
            listing(';demo.c:10: end'), listing('ret', 4), '    0000']
    data = parse_lst(iter(rows), ORIGIN).value
    assert len(data.lines[0].source.text) == 10000
    assert data.find_line('demo.c', 7).offset == 3
    assert data.find_line('demo.c', 8).source.line == 10
    assert data.find_line('demo.c', 11) is None
    assert data.find_line('other.c', 1) is None


def test_non_address_head_and_hex_in_source_are_not_offsets() -> None:
    result = parse_lst([listing('ld hl, 0x1234'), listing(';deadbeef'),
                        listing('nop', head='     00000001'), '    00000000', listing('nop', 2)], ORIGIN)
    assert [x.offset for x in result.value.lines] == [2]


def test_numeric_local_label_and_invalid_source_recovery() -> None:
    result = parse_lst([listing(';demo.c:0: invalid'), listing('00101$:', 0),
                        listing(';demo.c:1: valid'), listing('ret', 0)], ORIGIN)
    assert [d.code for d in result.diagnostics] == ['lst.invalid-source']
    assert result.value.labels[0].name == '00101$'
    assert result.value.lines[0].source.line == 1
