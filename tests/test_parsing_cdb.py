"""D09: raw CDB records survive order changes, errors and unresolved links."""

from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from msxdbg.debuginfo.cdb_parser import CdbData, CdbLink, parse_cdb
from msxdbg.debuginfo.diagnostics import ParseResult


ORIGIN = Path('build/demo.cdb')
FIXTURE = Path(__file__).parent / 'fixtures' / 'cdb' / 'scoped.cdb'


def parse(*rows):
    return parse_cdb(rows, ORIGIN)


def test_empty_and_irrelevant_records():
    for rows in ([], None, iter(()), ['', '  ', '; comment', '# comment', 'L:A$ignored']):
        result = parse_cdb(rows, ORIGIN)
        assert isinstance(result, ParseResult)
        assert result.value == CdbData()
        assert result.diagnostics == ()


def test_fixture_preserves_scope_storage_type_and_origins():
    result = parse_cdb(FIXTURE.read_text().splitlines(), FIXTURE)
    assert result.diagnostics == ()
    data = result.value
    assert [m.name for m in data.modules] == ['demo']
    assert data.modules[0].origin.line == 10
    first, second, temporary, global_ = data.symbols
    assert first.identity.raw == 'Ldemo.entry$value$1_2$3'
    assert (first.identity.module_key, first.identity.function_name) == ('demo', 'entry')
    assert (first.identity.level, first.identity.sublevel, first.identity.block) == (1, 2, 3)
    assert second.identity.raw == 'Ldemo.entry$value$2_0$4'
    assert first.type_chain.size == 2
    assert first.type_chain.raw == 'SI:S'
    assert first.type_chain.signed is True
    assert second.type_chain.signed is False
    assert (first.storage.code, first.storage.on_stack, first.storage.offset) == ('B', True, -6)
    assert second.storage.registers == ('l', 'h')
    assert second.storage.fallback.code == 'B'
    assert second.storage.fallback.offset == -8
    assert temporary.storage.registers == ('e', 'd')
    assert temporary.is_temporary is True
    assert first.is_temporary is False
    assert global_.storage.code == 'E'
    assert global_.identity.module_key is None
    assert first.origin.path == FIXTURE
    assert first.origin.line == 5


def test_links_are_not_guessed_as_functions_variables_or_lines():
    data = parse_cdb(FIXTURE.read_text().splitlines(), FIXTURE).value
    assert [(x.identity, x.address) for x in data.links] == [
        ('G$entry$0$0', 0x8000), ('G$counter$0$0', 0xC020),
        ('XFdemo$helper$0$0', 0x801F), ('Fdemo$helper$0$0', 0x8010),
    ]
    assert all(isinstance(x, CdbLink) for x in data.links)
    assert [x.identity.raw for x in data.functions] == ['G$entry$0$0', 'Fdemo$helper$0$0']
    assert not any(x.identity == 'XG$entry$0$0' for x in data.links)
    helper = data.functions[1]
    assert (helper.is_interrupt, helper.interrupt_number, helper.register_bank) == (True, 2, 3)
    source = data.lines[0]
    assert source.identity == 'C$src/demo.c$12$1_2$3'
    assert (source.source.path, source.source.line, source.address) == ('src/demo.c', 12, 0x8004)
    assert (source.level, source.sublevel, source.block) == (1, 2, 3)


def test_records_can_be_reordered_without_changing_meaning():
    rows = FIXTURE.read_text().splitlines()
    forward = parse_cdb(rows, ORIGIN)
    reverse = parse_cdb(reversed(rows), ORIGIN)
    assert reverse.diagnostics == forward.diagnostics == ()
    def without_origins(value):
        if isinstance(value, dict):
            return {k: without_origins(v) for k, v in value.items() if k != 'origin'}
        if isinstance(value, (tuple, list)):
            return tuple(without_origins(x) for x in value)
        return value

    for field in ('functions', 'symbols', 'links', 'lines', 'types', 'modules'):
        left = [without_origins(asdict(x)) for x in getattr(forward.value, field)]
        right = [without_origins(asdict(x)) for x in getattr(reverse.value, field)]
        assert left == list(reversed(right))


def test_modules_do_not_implicitly_own_globals_or_overwrite_scopes():
    data = parse('M:one', 'S:Ftwo$v$0$0({1}SC:U),E,0,0',
                 'M:three', 'S:G$g$0$0({1}SC:U),E,0,0',
                 'S:Ltwo.fn$arg$1$9({1}SC:U),B,1,4').value
    assert [x.identity.module_key for x in data.symbols] == ['two', None, 'two']
    assert data.symbols[-1].identity.sublevel is None
    assert [x.name for x in data.modules] == ['one', 'three']


def test_cross_file_and_duplicate_links_are_kept_for_loader():
    data = parse('L:G$elsewhere$0$0:1234', 'L:XG$elsewhere$0$0:FFFF',
                 'L:G$elsewhere$0$0:4321').value
    assert data.functions == data.symbols == ()
    assert [x.address for x in data.links] == [0x1234, 0xFFFF, 0x4321]
    assert [x.origin.line for x in data.links] == [1, 2, 3]
    assert parse('F:G$unlinked$0$0({2}DF,SV:S),C,0,0,0,0,0').value.links == ()


def test_duplicate_declarations_and_static_homonyms_do_not_collapse():
    rows = ['F:Fa$same$0$0({2}DF,SV:S),C,0,0,0,0,0',
            'F:Fb$same$0$0({2}DF,SV:S),C,0,0,0,0,0']
    data = parse(*rows, rows[0]).value
    assert [x.identity.module_key for x in data.functions] == ['a', 'b', 'a']
    assert [x.origin.line for x in data.functions] == [1, 2, 3]


def test_type_members_preserve_offsets_arrays_and_forward_self_reference():
    result = parse_cdb(FIXTURE.read_text().splitlines(), FIXTURE)
    type_ = result.value.types[0]
    assert (type_.identity, type_.module_key, type_.name) == ('Fdemo$Node', 'demo', 'Node')
    assert [x.offset for x in type_.fields] == [0, 2, 4]
    assert [x.symbol.identity.name for x in type_.fields] == ['next', 'value', 'bytes']
    assert [x.symbol.type_chain.raw for x in type_.fields] == ['DG,STNode:U', 'SI:S', 'DA4,SC:U']
    assert type_.fields[2].symbol.type_chain.size == 4
    assert type_.fields[0].symbol.origin.line == 14
    assert result.value.symbols[0].identity.scope != 'S'
    assert parse('T:Fdemo$Empty[]').value.types[0].fields == ()


def test_unknown_or_truncated_type_is_diagnostic_not_partial_success():
    result = parse('T:Fdemo$Bad[({0}S:S$ok$0$0({1}SC:U),Z,0,0)garbage]',
                   'T:Fdemo$Truncated[', 'T:G$unknown[]', 'T:Fdemo$Good[]')
    assert [x.name for x in result.value.types] == ['Good']
    assert [d.code for d in result.diagnostics] == ['cdb.unsupported-type'] * 3
    assert [d.origins[0].line for d in result.diagnostics] == [1, 2, 3]


@pytest.mark.parametrize('row', [
    None, b'M:bytes', 'M:', 'S:missing', 'F:G$fn$0$0({2}DF,SV:S),C,0,0',
    'S:G$v$bad$0({2}SI:S),E,0,0', 'S:G$v$0$-1({2}SI:S),E,0,0',
    'S:G$v$0$0({2}SI:Q),E,0,0', 'S:G$v$0$0({2}SI:S),R,0,0,[]',
    'S:G$v$0$0({2}SI:S),R,0,0,[l,,h]', 'S:G$v$0$0({2}SI:S),R,0,0',
    'S:G$v$0$0({2}SI:S),B,1,no', 'S:G$v$0$0({2}SI:S),E,2,0',
    'S:G$v$0$0({2}SI:S),E,0,0,[l,h]', 'L:G$v$0$0:xyz',
    'L:C$src.c$0$1_0$2:1234', 'L:C$src.c$5$1_0$-1:1234',
    'L:G$v$0$0', 'L:G$v$0$0:-1',
])
def test_malformed_record_has_origin_and_does_not_break_next_record(row):
    result = parse(row, 'S:G$valid$0$0({1}SC:U),E,0,0')
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].code == 'cdb.invalid-record'
    assert result.diagnostics[0].origins[0].path == ORIGIN
    assert result.diagnostics[0].origins[0].line == 1
    assert [x.identity.name for x in result.value.symbols] == ['valid']


def test_unsupported_records_and_overflow_do_not_wrap_addresses():
    result = parse('Q:unknown', 'S:G$v$0$0({2}SI:S),Q,0,0',
                   'L:G$v$0$0:10000', 'L:G$zero$0$0:0000')
    assert [d.code for d in result.diagnostics] == [
        'cdb.unsupported-record', 'cdb.unsupported-storage', 'cdb.address-out-of-range']
    assert [x.address for x in result.value.links] == [0]


def test_windows_source_path_dollar_in_path_and_line_variants():
    result = parse(r'L:C$C:\src\cost$dir\demo.c$37$2_4$9:aBcD',
                   'L:C$demo.c$40$2$9:FFFF')
    assert result.diagnostics == ()
    first, second = result.value.lines
    assert first.source.normalized_path == 'C:/src/cost$dir/demo.c'
    assert first.source.line == 37
    assert first.address == 0xABCD
    assert first.sublevel == 4
    assert second.sublevel is None


def test_long_line_generator_and_truncated_end():
    name = 'long_' + 'a' * 10000
    result = parse_cdb(iter([f'S:G${name}$0$0({{1}}SC:U),E,0,0', 'F:cut(']), ORIGIN)
    assert result.value.symbols[0].identity.name == name
    assert len(result.diagnostics) == 1
    assert result.diagnostics[0].origins[0].line == 2


def test_temporary_flag_does_not_hide_normal_names():
    result = parse(*(f'S:Ldemo.fn${name}$1$1({{1}}SC:U),E,0,0'
                     for name in ('sloc0', 'sloc123', 'sloc', 'sloc1_user', 'user_sloc1')))
    assert [x.is_temporary for x in result.value.symbols] == [True, True, False, False, False]


def test_records_and_collections_are_immutable():
    symbols = list(parse('S:G$v$0$0({1}SC:U),R,0,0,[a]').value.symbols)
    data = CdbData(symbols=symbols)
    symbols.clear()
    assert len(data.symbols) == 1
    with pytest.raises(FrozenInstanceError):
        data.symbols[0].storage.offset = 3


@pytest.mark.parametrize('chain', [
    'SC:U', 'SI:S', 'SS:S', 'SL:S', 'SF:S', 'SV:S',
    'DG,STNode:U', 'DC,SI:U', 'DX,SC:U', 'DD,SI:U',
    'DP,SC:U', 'DI,SC:U', 'DF,SV:S', 'DA4,SC:U',
])
def test_supported_member_type_encodings_are_preserved(chain):
    row = f'T:Fdemo$Type[({{0}}S:S$field$0$0({{4}}{chain}),Z,0,0)]'
    result = parse(row)
    assert result.diagnostics == ()
    assert result.value.types[0].fields[0].symbol.type_chain.raw == chain


def test_unsupported_member_type_does_not_certify_a_layout():
    result = parse('T:Fdemo$Bits[({0}S:S$bit$0$0({1}SB1:U),Z,0,0)]',
                   'T:Fdemo$Future[({0}S:S$field$0$0({1}UNKNOWN:U),Z,0,0)]')
    assert result.value.types == ()
    assert [d.code for d in result.diagnostics] == ['cdb.unsupported-type'] * 2


def test_unknown_declaration_type_is_preserved_without_invented_typedef():
    result = parse('S:G$future$0$0({4}FUTURE:U),E,0,0')
    assert result.diagnostics == ()
    assert result.value.symbols[0].type_chain.raw == 'FUTURE:U'
    assert result.value.types == ()
    assert result.value.links == ()


def test_rejected_type_member_does_not_leak_partial_fields_or_symbols():
    result = parse('T:Fdemo$Bad[({0}S:S$first$0$0({1}SC:U),Z,0,0)'
                   '({1}S:S$broken$0$0({2}SI:S),R,0,0,[])]',
                   'S:G$after$0$0({1}SC:U),E,0,0')
    assert result.value.types == ()
    assert [x.identity.name for x in result.value.symbols] == ['after']
    assert len(result.diagnostics) == 1


def test_register_order_is_preserved_without_normalizing_target_names():
    result = parse('S:Llegacy$arg$1$2({2}SI:U),R,0,0,[E,D]',
                   'S:Ldemo.fn$arg$1_0$2({2}SI:S),R,0,0,[l,h],B,1,4')
    assert result.diagnostics == ()
    assert result.value.symbols[0].storage.registers == ('E', 'D')
    assert result.value.symbols[0].identity.function_name == 'legacy'
    assert result.value.symbols[0].identity.module_key is None
    assert result.value.symbols[1].storage.fallback.offset == 4
