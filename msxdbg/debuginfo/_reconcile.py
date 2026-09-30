"""Private reconciliation of all artifacts belonging to one linked image."""
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from ._types import TypeResolver
from .diagnostics import Diagnostic
from .model import (AbsoluteStorage, AddressRange, Area, BlockScope, CodeLocation,
                    Function, FunctionId, Image, Module, ModuleId, RegisterStorage,
                    StackStorage, Symbol, UnknownStorage, Variable, VariableId)


CODE_AREAS = frozenset(("_CODE", "_HOME", "_GSINIT", "_GSFINAL"))


def _module_key(raw):
    path = Path(raw)
    return path.stem if path.suffix in ('.o', '.rel') else raw


def reconcile(image_id, maps, listings, cdbs, diagnostics):
    def warn(code, message, *origins):
        diagnostics.append(Diagnostic(code, 'warning', message, origins))

    symbols = []
    for data in maps:
        for raw in data.symbols:
            module = ModuleId(image_id, _module_key(raw.module_key)) if raw.module_key else None
            symbol = Symbol(raw.name, raw.address, module, raw.origin)
            if not any((s.name, s.address, s.module) == (symbol.name, symbol.address, symbol.module) for s in symbols):
                symbols.append(symbol)
    code_start = {s.address for s in symbols if s.name == 's__CODE'}
    code_size = {s.address for s in symbols if s.name == 'l__CODE'}
    code_extent = None
    if len(code_start) == len(code_size) == 1:
        start, size = next(iter(code_start)), next(iter(code_size))
        if size and start + size <= 0x10000:
            code_extent = AddressRange(start, start + size)
    modules = {}
    listing_records = {}
    duplicate_names = {name for name, count in Counter(x.module_name for x in listings).items() if count > 1}
    for data in listings:
        if data.module_name in duplicate_names:
            warn('load.duplicate-module', 'multiple listings claim module ' + data.module_name)
            continue
        listing_records[data.module_name] = data
        module_id = ModuleId(image_id, data.module_name)
        exports = {x.name for x in data.globals}
        candidate_bases = defaultdict(lambda: defaultdict(set))
        area_evidence = defaultdict(list)
        for label in data.labels:
            if label.area not in CODE_AREAS or label.name not in exports:
                continue
            matches = [s for s in symbols if s.name == label.name
                       and s.module in (None, module_id)]
            addresses = {s.address for s in matches}
            if len(addresses) != 1:
                if len(addresses) > 1:
                    warn('load.symbol-conflict', 'export has multiple linked addresses', label.origin,
                         *(s.origin for s in matches))
                continue
            base = next(iter(addresses)) - label.offset
            if not 0 <= base <= 0xFFFF:
                warn('load.invalid-base', 'module base would lie outside the CPU space', label.origin)
                continue
            candidate_bases[label.area][label.name].add(base)
            area_evidence[label.area].extend((label.origin, *(s.origin for s in matches)))
        selected_bases = {}
        for area_name in CODE_AREAS:
            candidates = candidate_bases[area_name]
            evidence = area_evidence[area_name]
            votes = {name: next(iter(values)) for name, values in candidates.items()
                     if len(values) == 1}
            if any(len(values) > 1 for values in candidates.values()):
                warn('load.label-conflict',
                     f'duplicate label has inconsistent offsets in {area_name}', *evidence)
            counts = Counter(votes.values())
            base = None
            if counts:
                best = max(counts.values())
                winners = [candidate for candidate, count in counts.items() if count == best]
                if len(winners) == 1:
                    base = winners[0]
                if len(counts) > 1:
                    warn('load.base-conflict' if base is not None else 'load.base-tie',
                         f'base candidates for {data.module_name}/{area_name}: {dict(counts)}',
                         *evidence)
            if base is not None:
                selected_bases[area_name] = base
            elif any(a.name == area_name for a in data.areas):
                warn('load.unresolved-base',
                     f'no unique {area_name} base for {data.module_name}', *evidence)
        areas = []
        for area in data.areas:
            base = selected_bases.get(area.name)
            offsets = [x.offset for x in data.lines if x.area == area.name]
            limit = (min(0x10000, base + max(offsets) + 17)
                     if base is not None and offsets else None)
            evidence = tuple(area_evidence[area.name])
            if limit is not None:
                warn('load.estimated-limit',
                     f'LST extent uses last known offset + 16 bytes for {data.module_name}/{area.name}',
                     *evidence)
            areas.append(Area(area.name, base, limit,
                              evidence + area.evidence if base is not None else area.evidence,
                              'lst-fallback' if limit is not None else None))
        areas = tuple(areas)
        labels = []
        locations = []
        if selected_bases:
            for label in data.labels:
                base = selected_bases.get(label.area)
                if base is not None and base + label.offset <= 0xFFFF:
                    labels.append(Symbol(label.name, base + label.offset, module_id, label.origin))
            for line in data.lines:
                base = selected_bases.get(line.area)
                if base is None:
                    continue
                if base + line.offset > 0xFFFF:
                    warn('load.address-overflow', 'relocated listing offset exceeds CPU space', line.origin)
                    continue
                locations.append(CodeLocation(image_id, base + line.offset, module_id, line.area,
                                              line.offset, line.source, evidence=(line.origin,)))
        modules[module_id] = Module(module_id, data.module_name, areas, tuple(labels),
            tuple(x for x in labels if x.name in exports),
            tuple(x.source for x in locations if x.source), tuple(locations))

    # Each distinct later base ends the preceding module's fallback extent.
    for id_, module in list(modules.items()):
        areas = []
        for area in module.areas:
            bases = sorted({a.base for m in modules.values() for a in m.areas
                            if a.name == area.name and a.base is not None})
            later = [b for b in bases if area.base is not None and b > area.base]
            if area.limit is not None and later:
                area = replace(area, limit=min(area.limit, later[0]))
            areas.append(area)
        by_name = {a.name: a for a in areas}
        locations = tuple(x for x in module.locations
                          if x.area in by_name and by_name[x.area].limit is not None
                          and x.address < by_name[x.area].limit)
        if len(locations) != len(module.locations):
            warn('load.listing-overlap', 'listing locations cross the next module base')
        modules[id_] = replace(module, areas=tuple(areas), locations=locations)

    raw_functions, raw_symbols, raw_types, links, lines = [], [], [], defaultdict(list), []
    for data in cdbs:
        raw_functions.extend(data.functions)
        raw_symbols.extend(data.symbols)
        raw_types.extend(data.types)
        lines.extend(data.lines)
        for link in data.links:
            links[link.identity].append(link)

    def linked(identity):
        found = links.get(identity, ())
        addresses = {x.address for x in found}
        if len(addresses) > 1:
            warn('load.link-conflict', 'conflicting addresses for ' + identity, *(x.origin for x in found))
            return None
        return next(iter(addresses)) if addresses else None

    def check_map_link(raw, address):
        if address is None:
            return
        matches = [s for s in symbols if s.name in (raw.identity.name, '_' + raw.identity.name)
                   and (raw.identity.module_key is None or s.module is None
                        or s.module.key == raw.identity.module_key)]
        if any(s.address != address for s in matches):
            warn('load.map-cdb-conflict', 'MAP and CDB addresses disagree for ' + raw.identity.raw,
                 raw.origin, *(s.origin for s in matches),
                 *(x.origin for x in links.get(raw.identity.raw, ())))

    def owner(raw):
        if raw.identity.module_key:
            return ModuleId(image_id, raw.identity.module_key)
        if raw.identity.function_name:
            owners = {f.id.module for f in functions if f.name == raw.identity.function_name}
            if len(owners) == 1:
                return next(iter(owners))
        matches = {s.module for s in symbols if s.name in (raw.identity.name, '_' + raw.identity.name)
                   and s.module is not None}
        if not matches:
            matches = {id_ for id_, m in modules.items() if any(s.name in
                       (raw.identity.name, '_' + raw.identity.name) for s in m.exports)}
        if len(matches) == 1:
            return next(iter(matches))
        warn('load.unresolved-owner', 'cannot assign module for ' + raw.identity.raw, raw.origin)
        return None

    def declarations(records):
        grouped = defaultdict(list)
        for raw in records:
            grouped[raw.identity.raw].append(raw)
        accepted = []
        for identity, group in grouped.items():
            first = group[0]
            if any(replace(item, origin=first.origin) != first for item in group[1:]):
                warn('load.declaration-conflict', 'conflicting declarations for ' + identity,
                     *(r.origin for r in group))
            else:
                accepted.append(first)
        return accepted

    collision = {x.identity.raw for x in raw_functions} & {x.identity.raw for x in raw_symbols}
    for identity in sorted(collision):
        warn('load.identity-conflict', 'identity declared as both function and variable: ' + identity)
    functions = []
    unsupported_ranges = []
    for raw in declarations(raw_functions):
        if raw.identity.raw in collision:
            continue
        module = owner(raw)
        entry = linked(raw.identity.raw)
        if module is None or entry is None or raw.storage.code not in ('C', 'Z'):
            warn('load.unresolved-function', 'function lacks proven code entry or owner', raw.origin)
            continue
        check_map_link(raw, entry)
        exit_ = linked('X' + raw.identity.raw)
        listing = listing_records.get(module.key)
        listing_label = next((label for label in listing.labels
                              if label.name in (raw.identity.name, '_' + raw.identity.name)), None) if listing else None
        function_area = listing_label.area if listing_label else '_CODE'
        if function_area not in CODE_AREAS:
            unsupported_ranges.append(AddressRange(entry, exit_ + 1 if exit_ is not None and exit_ >= entry else entry + 1))
            warn('load.unsupported-area', f'function is in non-code area {function_area}', raw.origin)
            continue
        end = exit_ + 1 if exit_ is not None and exit_ >= entry else None
        if exit_ is not None and exit_ < entry:
            warn('load.invalid-function-end', 'function exit precedes entry', raw.origin)
        evidence = (raw.origin,) + tuple(x.origin for x in links[raw.identity.raw])
        evidence += tuple(x.origin for x in links.get('X' + raw.identity.raw, ()))
        functions.append(Function(FunctionId(module, raw.identity.raw), raw.identity.name, entry,
                                  end, 'cdb-exit' if end is not None else None, evidence=evidence))
        modules.setdefault(module, Module(module, module.key))
    functions.sort(key=lambda f: (f.entry, f.id.module.key, f.id.record_identity))
    for index, function in enumerate(functions):
        next_entry = next((f.entry for f in functions[index + 1:] if f.entry > function.entry), None)
        if function.end is None and next_entry is not None:
            function = replace(function, end=next_entry, end_provenance='next-function')
        elif function.end is None and code_extent and code_extent.contains(function.entry):
            function = replace(function, end=code_extent.end_exclusive, end_provenance='map-code-area',
                evidence=function.evidence + tuple(s.origin for s in symbols if s.name in ('s__CODE', 'l__CODE')))
        elif function.end is not None and next_entry is not None and function.end > next_entry:
            warn('load.function-overlap', 'function exit overlaps a later entry', *function.evidence)
        function_lines = []
        for raw in lines:
            if raw.address < function.entry or function.end is not None and raw.address >= function.end:
                continue
            # Without an end, only exact entry lines can prove function membership.
            if function.end is None and raw.address != function.entry:
                continue
            owners = [f for f in functions if f.entry <= raw.address and
                      (f.end is None or raw.address < f.end)]
            latest = max((f.entry for f in owners), default=function.entry)
            if latest != function.entry:
                continue
            function_lines.append(raw)
        scopes = {}
        locations = []
        for raw in function_lines:
            key = (raw.level, raw.sublevel, raw.block)
            scopes.setdefault(key, []).append(raw.address)
            module = modules[function.id.module]
            listing = listing_records.get(function.id.module.key)
            label = next((x for x in listing.labels
                          if x.name in (function.name, '_' + function.name)), None) if listing else None
            area_name = label.area if label and label.area in CODE_AREAS else '_CODE'
            base = next((a.base for a in module.areas if a.name == area_name and a.base is not None), function.entry)
            locations.append(CodeLocation(image_id, raw.address, function.id.module, area_name,
                raw.address - base, raw.source, function.id, (raw.origin,)))
            for old in module.locations:
                if old.address == raw.address and old.source and (
                    old.source.normalized_path, old.source.line) != (raw.source.normalized_path, raw.source.line):
                    warn('load.source-conflict', 'CDB source overrides conflicting LST source',
                         *old.evidence, raw.origin)
        block_scopes = tuple(BlockScope(*key, AddressRange(min(values), max(values) + 1))
                             for key, values in sorted(scopes.items(), key=lambda x: str(x[0])))
        functions[index] = replace(function, lines=tuple(x.source for x in locations),
            blocks=tuple(x.extent for x in block_scopes), locations=tuple(locations), scopes=block_scopes)

    type_resolver = TypeResolver(image_id, raw_types, diagnostics)
    variables = []
    for raw in declarations(raw_symbols):
        if raw.is_temporary or raw.identity.raw in collision:
            continue
        module = owner(raw)
        if module is None:
            continue
        function = None
        if raw.identity.function_name:
            matches = [f for f in functions if f.id.module == module and f.name == raw.identity.function_name]
            if len(matches) != 1:
                warn('load.unresolved-local', 'local has no unique function', raw.origin)
                continue
            function = matches[0]
        allocation = raw.storage
        if allocation.code == 'R':
            storage = RegisterStorage(allocation.registers)
        elif allocation.on_stack or allocation.code == 'B':
            storage = StackStorage(allocation.offset)
        elif allocation.code in ('E', 'D', 'C'):
            address = linked(raw.identity.raw)
            check_map_link(raw, address)
            storage = AbsoluteStorage(address) if address is not None else UnknownStorage('missing or conflicting CDB link')
        else:
            storage = UnknownStorage('unsupported storage space ' + allocation.code)
        type_ = type_resolver.chain(raw.type_chain, module, raw.origin)
        is_parameter = bool(function and function.end is not None and function.scopes and not any(
            s.block == raw.identity.block for s in function.scopes))
        scope = 'local' if function else 'static' if raw.identity.scope.startswith('F') else 'global'
        variables.append(Variable(VariableId(module, raw.identity.raw), raw.identity.name,
            function.id if function else None, raw.identity.block, type_.id if type_ else None,
            storage, is_parameter, scope, raw.identity.level, raw.identity.sublevel, (raw.origin,)))
        modules.setdefault(module, Module(module, module.key))
    types = type_resolver.finish()
    image_locations = []
    seen_lines = set()
    for raw in lines:
        if any(extent.contains(raw.address) for extent in unsupported_ranges):
            continue
        key = (raw.identity, raw.address)
        if key in seen_lines:
            continue
        seen_lines.add(key)
        matches = [x for f in functions for x in f.locations
                   if x.address == raw.address and x.source == raw.source]
        if matches:
            image_locations.extend(matches)
            continue
        owners = [(m, a) for m in modules.values() for a in m.areas if a.name in CODE_AREAS
                  and a.base is not None and a.limit is not None and a.base <= raw.address < a.limit]
        if len(owners) == 1:
            module, area = owners[0]
            image_locations.append(CodeLocation(image_id, raw.address, module.id, area.name,
                raw.address - area.base, raw.source, evidence=(raw.origin,) + area.evidence))
        else:
            image_locations.append(CodeLocation(image_id, raw.address, area='_CODE',
                                                source=raw.source, evidence=(raw.origin,)))
    return Image(image_id, tuple(modules.values()), tuple(symbols), tuple(functions),
                 tuple(variables), types, tuple(diagnostics), tuple(image_locations))
