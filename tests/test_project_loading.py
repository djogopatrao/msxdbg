"""Offline integration: discovery, reconciliation and queries use no target."""
from pathlib import Path

import pytest

from msxdbg.debuginfo.diagnostics import ProjectLoadError
from msxdbg.debuginfo.index import Project, SymbolContext, VariableKind
from msxdbg.debuginfo.loader import ImageSpec, ProjectLoader, ProjectSpec
from msxdbg.debuginfo.model import (AbsoluteStorage, ImageId, ModuleId, RegisterStorage,
                                  StackStorage, TypeId, UnknownStorage)


def lst(text, offset=None):
    head = '' if offset is None else f'    {offset:08X} 00 [4]'
    return f'{head:<34}{1:5} {text}'


def write_module(root, name, base, source=None, labels=None, offsets=(0, 4, 8)):
    root.mkdir(parents=True, exist_ok=True)
    source = source or f'src/{name}.c'
    labels = labels or [(f'_{name}', 0, base)]
    rows = [lst('.module ' + name), lst('.area _CODE')]
    for symbol, offset, _ in labels:
        rows += [lst('.globl ' + symbol), lst(symbol + ':', offset)]
    for line, offset in enumerate(offsets, 10):
        rows += [lst(f';{source}:{line}: source {line}'), lst('nop', offset)]
    rows += [lst('.area _HOME'), lst(';init.c:1: init'), lst('nop', 0)]
    (root / f'{name}.lst').write_text('\n'.join(rows))
    map_rows = ['Value Global'] + [f'{address:08X} {symbol} {name}' for symbol, _, address in labels]
    (root / f'{name}.map').write_text('\n'.join(map_rows))


def load(root, name='resident', **kwargs):
    return ProjectLoader().load(ProjectSpec((ImageSpec(ImageId(name), root, **kwargs),)))


def add_cdb(root):
    # Links deliberately live in a different file and precede declarations.
    (root / 'addresses.cdb').write_text('\n'.join([
        'L:G$main$0$0:8000', 'L:XG$main$0$0:800F',
        'L:G$count$0$0:C020', 'L:C$src/main.c$20$1_0$1:8004',
        'L:C$src/main.c$22$2_1$2:8008', 'L:C$src/main.c$23$1_0$1:800C',
    ]))
    (root / 'main.cdb').write_text('\n'.join([
        'M:main', 'F:G$main$0$0({2}DF,SV:S),C,0,0,0,0,0',
        'S:G$count$0$0({2}SI:U),E,0,0',
        'S:Lmain.main$arg$1_0$9({2}SI:S),B,1,4',
        'S:Lmain.main$value$1_0$1({2}SI:S),B,1,-4',
        'S:Lmain.main$value$2_1$2({2}SI:U),R,0,0,[l,h]',
        'S:Lmain.main$sloc1$1_0$1({1}SC:U),R,0,0,[a]',
        'S:Fmain$unlinked$0$0({1}SC:U),E,0,0',
    ]))
    with (root / 'main.map').open('a') as stream:
        stream.write('\n0000C020 _count main\n')


def test_discovery_is_sorted_and_empty_overrides_disable_discovery(tmp_path):
    write_module(tmp_path / 'z', 'z', 0x9000)
    write_module(tmp_path / 'a', 'a', 0x8000)
    (tmp_path / 'z' / 'z.cdb').write_text('M:z')
    loader = ProjectLoader()
    found = loader.discover(ImageSpec(ImageId('x'), tmp_path))
    assert [p.name for p in found.maps] == ['a.map', 'z.map']
    assert [p.name for p in found.listings] == ['a.lst', 'z.lst']
    explicit = loader.discover(ImageSpec(ImageId('x'), tmp_path, maps=[], cdbs=[]))
    assert explicit.maps == explicit.cdbs == ()
    assert explicit.listings == found.listings
    chosen = loader.discover(ImageSpec(ImageId('x'), tmp_path, maps=(found.maps[1],)))
    assert chosen.maps == (found.maps[1],)


def test_missing_directory_and_explicit_missing_file_have_origins(tmp_path):
    with pytest.raises(ProjectLoadError) as error:
        load(tmp_path / 'missing')
    assert error.value.diagnostics[0].code == 'load.missing-directory'
    with pytest.raises(ProjectLoadError) as error:
        load(tmp_path, maps=(tmp_path / 'absent.map',))
    assert error.value.diagnostics[0].origins[0].path == tmp_path / 'absent.map'


def test_duplicate_ids_fail_before_discovery_or_parsing(tmp_path, monkeypatch):
    loader = ProjectLoader()
    monkeypatch.setattr(loader, 'discover', lambda spec: pytest.fail('must validate ids first'))
    spec = ImageSpec(ImageId('same'), tmp_path)
    with pytest.raises(ProjectLoadError) as error:
        loader.load(ProjectSpec((spec, spec)))
    assert error.value.diagnostics[0].code == 'load.duplicate-image'


def test_essential_map_missing_empty_or_disabled_is_failure(tmp_path):
    with pytest.raises(ProjectLoadError):
        load(tmp_path)
    (tmp_path / 'bad.map').write_text('not a symbol table')
    with pytest.raises(ProjectLoadError) as error:
        load(tmp_path)
    assert error.value.diagnostics[-1].code == 'load.empty-map'
    write_module(tmp_path, 'main', 0x8000)
    with pytest.raises(ProjectLoadError):
        load(tmp_path, maps=[])


def test_lst_module_ownership_boundaries_gaps_and_source_lookup(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    write_module(tmp_path, 'next', 0x8010)
    loaded = load(tmp_path)
    project = loaded.project
    assert project.resolve(0x7FFF).status == 'missing'
    assert project.resolve(0x8000).unique_or_none().module.key == 'main'
    assert project.resolve(0x800F).unique_or_none().module.key == 'main'
    assert project.resolve(0x8010).unique_or_none().module.key == 'next'
    assert project.resolve(0x8028).unique_or_none().module.key == 'next'
    assert project.resolve(0x8029).status == 'missing'
    assert project.resolve_line('init.c', 1).status == 'missing'
    exact = project.resolve_line('main.c', 11).unique_or_none()
    assert (exact.effective_line, exact.location.address) == (11, 0x8004)
    assert project.resolve_line('main.c', 13).status == 'missing'
    assert any(d.code == 'load.estimated-limit' for d in loaded.diagnostics)
    assert project.resolve(0x8000).unique_or_none().evidence


def test_majority_base_wins_with_warning_and_tie_stays_unknown(tmp_path):
    labels = [('_a', 0, 0x8000), ('_b', 4, 0x8004), ('_c', 8, 0x9008)]
    write_module(tmp_path, 'main', 0x8000, labels=labels)
    result = load(tmp_path)
    assert result.project.resolve(0x8000).status == 'unique'
    assert any(d.code == 'load.base-conflict' for d in result.diagnostics)
    write_module(tmp_path, 'main', 0x8000, labels=[('_a', 0, 0x8000), ('_b', 4, 0x9004)])
    result = load(tmp_path)
    assert result.project.resolve(0x8000).status == 'missing'
    assert result.project.resolve_line('main.c', 10).status == 'missing'
    assert any(d.code == 'load.base-tie' for d in result.diagnostics)


def test_map_nearest_symbol_does_not_assign_module_ownership(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    with (tmp_path / 'main.map').open('a') as stream:
        stream.write('\n00008006 _foreign other\n')
    project = load(tmp_path).project
    assert project.nearest_symbol(0x8008).unique_or_none().symbol.module.key == 'other'
    assert project.resolve(0x8008).unique_or_none().module.key == 'main'
    assert project.nearest_symbol(0x7FFF).status == 'missing'


def test_multi_image_preserves_ambiguity_and_image_filter(tmp_path):
    roots = (tmp_path / 'resident', tmp_path / 'overlay')
    for root in roots:
        write_module(root, 'main', 0x8000)
    specs = tuple(ImageSpec(ImageId(root.name), root) for root in roots)
    project = ProjectLoader().load(ProjectSpec(specs)).project
    assert project.resolve(0x8004).status == 'ambiguous'
    assert project.lookup_symbol('_main').status == 'ambiguous'
    assert project.nearest_symbol(0x8004).status == 'ambiguous'
    assert project.resolve_line('main.c', 10).status == 'ambiguous'
    assert project.resolve(0x8004, ImageId('overlay')).unique_or_none().image == ImageId('overlay')
    assert project.lookup_symbol('_main', ImageId('resident')).status == 'unique'


def test_path_matching_uses_components_and_next_line_per_file(tmp_path):
    write_module(tmp_path / 'a', 'a', 0x8000, 'left/map.c')
    write_module(tmp_path / 'b', 'b', 0x9000, 'right/map.c')
    write_module(tmp_path / 'c', 'c', 0xA000, 'worldmap.c')
    project = load(tmp_path).project
    result = project.resolve_line('map.c', 9)
    assert result.status == 'ambiguous'
    assert [x.effective_line for x in result.candidates] == [10, 10]
    assert project.resolve_line('left/map.c', 9).unique_or_none().location.address == 0x8000
    assert project.resolve_line('worldmap.c', 9).status == 'unique'
    assert project.resolve_line('ap.c', 9).status == 'missing'


def test_exact_symbol_precedes_alias_and_completion_keeps_qualification(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    with (tmp_path / 'main.map').open('a') as stream:
        stream.write('\n00009000 main main\n')
    project = load(tmp_path).project
    assert project.lookup_symbol('main').unique_or_none().address == 0x9000
    assert project.lookup_symbol('_main').unique_or_none().address == 0x8000
    assert project.lookup_symbol('absent').status == 'missing'
    catalog = project.completion_catalog()
    assert 'resident::_main' in catalog.symbols
    assert catalog.symbols == tuple(sorted(catalog.symbols))
    assert 'src/main.c' in catalog.files


def test_cross_file_cdb_links_scopes_storage_and_precedence(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    add_cdb(tmp_path)
    project = load(tmp_path).project
    function = project.function_at(0x800F).unique_or_none()
    assert (function.entry, function.end, function.end_provenance) == (0x8000, 0x8010, 'cdb-exit')
    assert project.function_at(0x8010).status == 'missing'
    assert project.resolve(0x8008).unique_or_none().source.line == 22
    assert project.resolve_line('main.c', 21).unique_or_none().effective_line == 22
    context = SymbolContext(ImageId('resident'), function.id.module, function.id, 0x8008)
    variables = project.variables_in_scope(context, VariableKind.ALL)
    assert {v.name for v in variables} == {'arg', 'value'}
    assert len(variables) == 3
    assert not any(v.name.startswith('sloc') for v in project.images[0].variables)
    assert isinstance(project.find_variable('value', context).unique_or_none().storage, RegisterStorage)
    assert project.find_variable('value', context).unique_or_none().storage.registers == ('l', 'h')
    assert isinstance(project.find_variable('arg', context).unique_or_none().storage, StackStorage)
    assert project.find_variable('arg', context).unique_or_none().storage.offset == 4
    assert isinstance(project.find_variable('count', context).unique_or_none().storage, AbsoluteStorage)
    assert project.find_variable('count', context).unique_or_none().storage.address == 0xC020
    assert isinstance(project.find_variable('unlinked', context).unique_or_none().storage, UnknownStorage)
    before = SymbolContext(context.image, context.module, context.function, 0x8000)
    assert project.variables_in_scope(before, VariableKind.ALL) == ()
    assert len(project.variables_in_scope(context, VariableKind.PARAMETERS)) == 1
    assert len(project.variables_in_scope(context, VariableKind.LOCALS)) == 2
    later = SymbolContext(context.image, context.module, context.function, 0x800C)
    assert project.find_variable('value', later).unique_or_none().storage.offset == -4


def test_missing_exit_is_bounded_by_next_entry_but_final_is_not_infinite(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    (tmp_path / 'main.cdb').write_text('\n'.join([
        'F:Fmain$first$0$0({2}DF,SV:S),C,0,0,0,0,0',
        'F:Fmain$last$0$0({2}DF,SV:S),C,0,0,0,0,0',
        'L:Fmain$first$0$0:8000', 'L:Fmain$last$0$0:8010',
    ]))
    project = load(tmp_path).project
    first = project.function_at(0x800F).unique_or_none()
    assert first.name == 'first' and first.end_provenance == 'next-function'
    assert project.function_at(0x8010).unique_or_none().name == 'last'
    assert project.function_at(0x8011).status == 'missing'
    assert project.function_at(0xFFFF).status == 'missing'


def test_conflicting_links_and_declarations_do_not_pick_first(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    add_cdb(tmp_path)
    (tmp_path / 'extra.cdb').write_text('L:G$main$0$0:9000\nL:G$count$0$0:C030\n')
    loaded = load(tmp_path)
    assert loaded.project.function_at(0x8000).status == 'missing'
    count = next(v for v in loaded.project.images[0].variables if v.name == 'count')
    assert isinstance(count.storage, UnknownStorage)
    assert any(d.code == 'load.link-conflict' for d in loaded.diagnostics)


def test_types_have_provenance_and_cycles_fail_independently(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    (tmp_path / 'main.cdb').write_text('\n'.join([
        'T:Fmain$Node[({0}S:S$next$0$0({2}DG,STNode:U),Z,0,0)({2}S:S$value$0$0({2}SI:S),Z,0,0)]',
        'T:Fmain$Cycle[({0}S:S$self$0$0({2}STCycle:U),Z,0,0)]',
        'T:Fmain$Dependent[({0}S:S$bad$0$0({2}STCycle:U),Z,0,0)]',
        'T:Fmain$Good[({0}S:S$n$0$0({2}SI:U),Z,0,0)]',
    ]))
    loaded = load(tmp_path)
    project = loaded.project
    node = project.lookup_type('Node').unique_or_none()
    assert node.size == 4 and node.evidence[0].path.name == 'main.cdb'
    pointer = project.type_by_id(node.fields[0].type_id)
    assert pointer.referenced_type == node.id
    assert project.lookup_type('Cycle').status == 'missing'
    assert project.lookup_type('Dependent').status == 'missing'
    assert project.lookup_type('Good').unique_or_none().size == 2
    assert project.lookup_type('int').unique_or_none().name == 'i16'
    with pytest.raises(KeyError):
        project.type_by_id(TypeId('missing'))
    assert any(d.code == 'load.invalid-type' for d in loaded.diagnostics)


def test_optional_headers_are_explicitly_unavailable_without_breaking_code(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    spec = ProjectSpec((ImageSpec(ImageId('resident'), tmp_path),), struct_headers=(tmp_path / 'types.h',))
    loaded = ProjectLoader().load(spec)
    assert loaded.project.resolve(0x8000).status == 'unique'
    assert any(d.code == 'load.headers-unavailable' for d in loaded.diagnostics)


def test_invalid_query_arguments():
    project = Project(())
    for method in (project.resolve, project.nearest_symbol, project.function_at):
        with pytest.raises(ValueError):
            method(0x10000)
    with pytest.raises(ValueError):
        project.resolve_line('main.c', 0)


def test_unreadable_artifact_reports_failure_not_empty_discovery(tmp_path, monkeypatch):
    write_module(tmp_path, 'main', 0x8000)
    original = Path.open
    def denied(path, *args, **kwargs):
        if path.suffix == '.map':
            raise PermissionError('fixture access denied')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', denied)
    with pytest.raises(ProjectLoadError) as error:
        load(tmp_path)
    assert error.value.diagnostics[0].code == 'load.unreadable-artifact'


def test_map_module_object_suffix_and_duplicate_symbols(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    (tmp_path / 'main.map').write_text('Value Global\n00008000 _main main.rel\n00008000 _main main.rel\n')
    project = load(tmp_path).project
    assert project.lookup_symbol('_main').status == 'unique'
    assert project.resolve(0x8004).unique_or_none().module.key == 'main'


def test_duplicate_listing_module_does_not_choose_arbitrary_base(tmp_path):
    write_module(tmp_path / 'a', 'main', 0x8000)
    write_module(tmp_path / 'b', 'main', 0x9000)
    loaded = load(tmp_path)
    assert loaded.project.resolve(0x8000).status == 'missing'
    assert loaded.project.resolve(0x9000).status == 'missing'
    assert any(d.code == 'load.duplicate-module' for d in loaded.diagnostics)


def test_relocation_overflow_is_diagnostic_and_does_not_wrap(tmp_path):
    write_module(tmp_path, 'main', 0xFFFC)
    loaded = load(tmp_path)
    assert any(d.code == 'load.address-overflow' for d in loaded.diagnostics)
    assert loaded.project.resolve(0).status == 'missing'
    assert loaded.project.resolve(0xFFFF).status == 'unique'
    assert loaded.project.resolve_line('main.c', 11).status == 'missing'


def test_known_home_function_and_lines_stay_unsupported(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    with (tmp_path / 'main.lst').open('a') as stream:
        stream.write('\n' + lst('_init:', 0) + '\n')
    with (tmp_path / 'main.map').open('a') as stream:
        stream.write('\n00007000 _init main\n')
    (tmp_path / 'main.cdb').write_text('\n'.join([
        'F:G$init$0$0({2}DF,SV:S),C,0,0,0,0,0',
        'L:G$init$0$0:7000', 'L:XG$init$0$0:7005',
        'L:C$init.c$1$1$1:7000',
    ]))
    project = load(tmp_path).project
    assert project.function_at(0x7000).status == 'missing'
    assert project.resolve(0x7000).status == 'missing'
    assert project.resolve_line('init.c', 1).status == 'missing'


def test_cdb_symbol_identity_never_becomes_a_function(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    (tmp_path / 'main.cdb').write_text('\n'.join([
        'S:Fmain$value$0$0({2}SI:U),E,0,0', 'L:Fmain$value$0$0:8000',
        'L:XFmain$value$0$0:800F',
    ]))
    project = load(tmp_path).project
    assert project.function_at(0x8000).status == 'missing'
    assert project.images[0].variables[0].storage.address == 0x8000


def test_final_function_at_ffff_has_exclusive_end_10000(tmp_path):
    write_module(tmp_path, 'main', 0xFFFF, offsets=(0,))
    (tmp_path / 'main.cdb').write_text('\n'.join([
        'F:G$main$0$0({2}DF,SV:S),C,0,0,0,0,0',
        'L:G$main$0$0:FFFF', 'L:XG$main$0$0:FFFF',
    ]))
    function = load(tmp_path).project.function_at(0xFFFF).unique_or_none()
    assert function.end == 0x10000


def test_scoped_queries_preserve_multi_image_ambiguity(tmp_path):
    specs = []
    for name in ('resident', 'overlay'):
        root = tmp_path / name
        write_module(root, 'main', 0x8000)
        add_cdb(root)
        specs.append(ImageSpec(ImageId(name), root))
    project = ProjectLoader().load(ProjectSpec(specs)).project
    context = SymbolContext(None, None, None, 0x8008)
    assert project.function_at(0x8008).status == 'ambiguous'
    assert project.find_variable('value', context).status == 'ambiguous'
    assert project.variables_in_scope(context, VariableKind.ALL) == ()
    assert project.lookup_type('i16').status == 'unique'


def test_statics_homonyms_and_type_names_do_not_collapse(tmp_path):
    for name, base in (('a', 0x8000), ('b', 0x9000)):
        write_module(tmp_path, name, base)
        (tmp_path / (name + '.cdb')).write_text('\n'.join([
            f'F:F{name}$helper$0$0({{2}}DF,SV:S),C,0,0,0,0,0',
            f'L:F{name}$helper$0$0:{base:04X}', f'L:XF{name}$helper$0$0:{base+15:04X}',
            f'S:F{name}$state$0$0({{1}}SC:U),E,0,0',
            f'L:F{name}$state$0$0:{base+20:04X}',
            f'T:F{name}$Thing[({{0}}S:S$n$0$0({{1}}SC:U),Z,0,0)]',
        ]))
    project = load(tmp_path).project
    assert project.function_at(0x8000).unique_or_none().id != project.function_at(0x9000).unique_or_none().id
    assert project.lookup_type('Thing').status == 'ambiguous'
    context = SymbolContext(ImageId('resident'), ModuleId(ImageId('resident'), 'a'), None, 0x8000)
    assert project.find_variable('state', context).unique_or_none().storage.address == 0x8014
    assert project.find_variable('state', SymbolContext(None, None, None, 0)).status == 'ambiguous'


def test_cdb_source_conflict_has_both_origins_and_cdb_offset(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    add_cdb(tmp_path)
    loaded = load(tmp_path)
    conflict = next(d for d in loaded.diagnostics if d.code == 'load.source-conflict')
    assert {o.path.suffix for o in conflict.origins} == {'.lst', '.cdb'}
    assert loaded.project.resolve_line('main.c', 22).unique_or_none().location.offset == 8


def test_cdb_lines_without_function_survive_with_known_source(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    (tmp_path / 'main.cdb').write_text('L:C$src/main.c$50$1$1:8004\n')
    project = load(tmp_path).project
    location = project.resolve_line('main.c', 50).unique_or_none().location
    assert location.address == 0x8004 and location.function is None
    assert project.resolve(0x8004).unique_or_none().source.line == 50


def test_types_reject_overlapping_layout_and_preserve_independent_arrays(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    (tmp_path / 'main.cdb').write_text('\n'.join([
        'T:Fmain$Overlap[({0}S:S$a$0$0({2}SI:U),Z,0,0)({0}S:S$b$0$0({1}SC:U),Z,0,0)]',
        'T:Fmain$Array[({0}S:S$bytes$0$0({4}DA4,SC:U),Z,0,0)]',
        'S:Fmain$unknown$0$0({2}FUTURE:U),E,0,0',
    ]))
    loaded = load(tmp_path)
    assert loaded.project.lookup_type('Overlap').status == 'missing'
    array = loaded.project.lookup_type('Array').unique_or_none()
    field = loaded.project.type_by_id(array.fields[0].type_id)
    assert field.category == 'array' and field.array_count == 4
    assert next(v for v in loaded.project.images[0].variables if v.name == 'unknown').type_id is None


def test_loading_and_queries_do_not_open_network_connections(tmp_path, monkeypatch):
    import socket
    write_module(tmp_path, 'main', 0x8000)
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('offline load opened a socket'))
    project = load(tmp_path).project
    assert project.resolve(0x8000).status == 'unique'
    assert project.lookup_symbol('main').status == 'unique'
    assert project.completion_catalog().files


def test_last_function_uses_proven_map_area_end(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    with (tmp_path / 'main.map').open('a') as stream:
        stream.write('\n00008000 s__CODE\n00000020 l__CODE\n')
    (tmp_path / 'main.cdb').write_text('F:G$main$0$0({2}DF,SV:S),C,0,0,0,0,0\nL:G$main$0$0:8000\n')
    project = load(tmp_path).project
    function = project.function_at(0x801F).unique_or_none()
    assert function.end == 0x8020 and function.end_provenance == 'map-code-area'
    assert project.function_at(0x8020).status == 'missing'


def test_parameter_detection_uses_block_not_sublevel(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    (tmp_path / 'main.cdb').write_text('\n'.join([
        'F:G$main$0$0({2}DF,SV:S),C,0,0,0,0,0',
        'L:G$main$0$0:8000', 'L:XG$main$0$0:8010',
        'L:C$src/main.c$20$1_1$1:8004', 'L:C$src/main.c$21$1_2$1:8008',
        'S:Lmain.main$local$1_0$1({2}SI:S),B,1,-2',
    ]))
    project = load(tmp_path).project
    variable = project.images[0].variables[0]
    assert variable.is_parameter is False
    context = SymbolContext(ImageId('resident'), variable.id.module, variable.function, 0x8006)
    assert project.find_variable('local', context).unique_or_none() == variable
    assert project.variables_in_scope(context, VariableKind.PARAMETERS) == ()


def test_malformed_nested_type_does_not_abort_load(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    (tmp_path / 'main.cdb').write_text('S:Fmain$bad$0$0({2}DG,DA2:U),E,0,0\n')
    loaded = load(tmp_path)
    assert loaded.project.images[0].variables[0].type_id is None
    assert any(d.code == 'load.unsupported-type' for d in loaded.diagnostics)


def test_context_function_identifies_image_for_global_fallback(tmp_path):
    specs = []
    for name in ('resident', 'overlay'):
        root = tmp_path / name
        write_module(root, 'main', 0x8000)
        add_cdb(root)
        specs.append(ImageSpec(ImageId(name), root))
    project = ProjectLoader().load(ProjectSpec(specs)).project
    function = project.function_at(0x8004, ImageId('resident')).unique_or_none()
    context = SymbolContext(None, None, function.id, 0x8004)
    assert project.find_variable('count', context).unique_or_none().id.module.image == ImageId('resident')


def test_unknown_scope_does_not_prioritize_static_over_global(tmp_path):
    write_module(tmp_path, 'main', 0x8000)
    with (tmp_path / 'main.map').open('a') as stream:
        stream.write('\n0000C000 _value main\n')
    (tmp_path / 'main.cdb').write_text('S:G$value$0$0({1}SC:U),E,0,0\nS:Fother$value$0$0({1}SC:U),E,0,0\n')
    project = load(tmp_path).project
    assert project.find_variable('value', SymbolContext(None, None, None, 0)).status == 'ambiguous'
