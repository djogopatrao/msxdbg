"""Private type reconciliation for the supported Z80 CDB subset."""
from dataclasses import replace

from .diagnostics import Diagnostic
from .model import Field, ModuleId, TypeDef, TypeId


PRIMITIVES = tuple(
    TypeDef(TypeId(name), name, category, size, signed)
    for name, category, size, signed in (
        ('bool', 'integer', 1, False), ('i8', 'integer', 1, True),
        ('u8', 'integer', 1, False), ('c8', 'character', 1, False),
        ('i16', 'integer', 2, True), ('u16', 'integer', 2, False),
        ('c16', 'character', 2, False), ('i32', 'integer', 4, True),
        ('u32', 'integer', 4, False), ('i64', 'integer', 8, True),
        ('u64', 'integer', 8, False), ('f32', 'float', 4, True),
        ('ptr', 'pointer', 2, False), ('void', 'void', 0, None),
    )
)
TYPE_ALIASES = {'char': 'c8', 'int': 'i16', 'short': 'i16', 'unsigned': 'u16',
                'unsigned int': 'u16', 'long': 'i32', 'float': 'f32',
                'unsigned char': 'u8', 'signed char': 'i8'}
_PRIMITIVE = {t.name: t for t in PRIMITIVES}


class TypeResolver:
    def __init__(self, image, records, diagnostics):
        self.image = image
        self.diagnostics = diagnostics
        self.records = {}
        self.types = {}
        self.active = set()
        self.invalid = set()
        for record in records:
            key = (record.module_key, record.name)
            old = self.records.get(key)
            if old is not None:
                # Repeated identical T records across linked artifacts are common.
                signature = lambda r: tuple((f.offset, f.symbol.identity.raw,
                    f.symbol.type_chain) for f in r.fields)
                if signature(old) != signature(record):
                    self.invalid.add(key)
                    self.warn('load.type-conflict', 'conflicting CDB type declarations', old.origin, record.origin)
            else:
                self.records[key] = record

    def warn(self, code, message, *origins):
        self.diagnostics.append(Diagnostic(code, 'warning', message, origins))

    def struct_id(self, module, name):
        return TypeId('T:' + name, self.image, ModuleId(self.image, module))

    def struct(self, module, name):
        key = (module, name)
        id_ = self.struct_id(module, name)
        if key in self.invalid:
            raise ValueError('invalid dependent type ' + name)
        if id_ in self.types:
            return self.types[id_]
        if len(self.active) >= 128:
            raise ValueError("type nesting exceeds supported depth")
        if key in self.active:
            self.invalid.add(key)
            raise ValueError('recursive composition by value: ' + name)
        record = self.records.get(key)
        if record is None:
            raise ValueError('incomplete type ' + name)
        self.active.add(key)
        try:
            fields = []
            size = 0
            names = set()
            for field in record.fields:
                if field.symbol.identity.name in names or field.offset != size:
                    raise ValueError('unsupported overlapping, padded or duplicate member layout')
                names.add(field.symbol.identity.name)
                child = self.chain(field.symbol.type_chain, ModuleId(self.image, module), field.symbol.origin)
                if child is None or child.size is None:
                    raise ValueError('incomplete member type')
                fields.append(Field(field.symbol.identity.name, child.id, field.offset))
                size += child.size
            type_ = TypeDef(id_, name, 'struct', size, fields=tuple(fields), evidence=(record.origin,))
            self.types[id_] = type_
            return type_
        except ValueError:
            self.invalid.add(key)
            raise
        finally:
            self.active.remove(key)

    def chain(self, chain, module, origin):
        previous_ids = set(self.types)
        try:
            tokens = chain.raw.rsplit(':', 1)[0].split(',')
            if len(tokens) > 64:
                raise ValueError("type chain exceeds supported depth")
            result = self._chain(tokens, chain.signed, chain.size, module, origin)
            if result.size != chain.size:
                raise ValueError('declared size differs from supported type layout')
            return result
        except ValueError as exc:
            for id_ in set(self.types) - previous_ids:
                del self.types[id_]
            self.warn('load.unsupported-type', str(exc), origin)
            return None

    def _chain(self, tokens, signed, size, module, origin):
        token, rest = tokens[0], tokens[1:]
        module_key = module.key
        id_ = TypeId('chain:' + ','.join(tokens) + (':S' if signed else ':U') + f':{size}', self.image, module)
        if token in ('DG', 'DC', 'DD', 'DX', 'DP', 'DI'):
            if not rest or size != 2:
                raise ValueError('unsupported pointer encoding/width')
            if len(rest) == 1 and rest[0].startswith('ST'):
                name = rest[0][2:]
                child_id = self.struct_id(module_key, name)
                # Pointer cycles are legal; value-layout validation is deferred.
                if (module_key, name) not in self.records:
                    self.types.setdefault(child_id, TypeDef(child_id, name, 'incomplete', evidence=(origin,)))
            else:
                child = self._chain(rest, signed, self._size(rest, module_key), module, origin)
                child_id = child.id
            result = TypeDef(id_, ','.join(tokens), 'pointer', 2, False, child_id, evidence=(origin,))
        elif token.startswith('DA') and token[2:].isdigit() and rest:
            count = int(token[2:])
            child_size = self._size(rest, module_key)
            child = self._chain(rest, signed, child_size, module, origin)
            result = TypeDef(id_, ','.join(tokens), 'array', count * child_size, signed,
                             child.id, array_count=count, evidence=(origin,))
        elif not rest and token.startswith('ST'):
            return self.struct(module_key, token[2:])
        elif not rest and token in ('SC', 'SI', 'SS', 'SL', 'SV', 'SF'):
            name = {'SC': 'i8' if signed else 'u8', 'SI': 'i16' if signed else 'u16',
                    'SS': 'i16' if signed else 'u16', 'SL': 'i32' if signed else 'u32',
                    'SV': 'void', 'SF': 'f32'}[token]
            # A CDB-origin instance keeps provenance while primitive ids stay global.
            result = replace(_PRIMITIVE[name], id=id_, evidence=(origin,))
        else:
            raise ValueError('unsupported CDB type chain: ' + ','.join(tokens))
        self.types.setdefault(id_, result)
        return self.types[id_]

    def _size(self, tokens, module):
        if not tokens:
            raise ValueError("incomplete type chain")
        token = tokens[0]
        if token in ('DG', 'DC', 'DD', 'DX', 'DP', 'DI'):
            return 2
        if token.startswith('DA') and token[2:].isdigit():
            return int(token[2:]) * self._size(tokens[1:], module)
        if token.startswith('ST'):
            return self.struct(module, token[2:]).size
        sizes = {'SC': 1, 'SI': 2, 'SS': 2, 'SL': 4, 'SV': 0, 'SF': 4}
        if token not in sizes:
            raise ValueError('unknown CDB type')
        return sizes[token]

    def finish(self):
        for module, name in self.records:
            try:
                self.struct(module, name)
            except ValueError as exc:
                self.warn('load.invalid-type', str(exc), self.records[module, name].origin)
        # Keep unresolved pointer targets explicit; never expose a rejected struct as usable.
        for module, name in self.invalid:
            id_ = self.struct_id(module, name)
            self.types[id_] = TypeDef(id_, name, 'incomplete')
        return tuple(self.types.values())
