import json
from pathlib import Path

from msxdbg.debuginfo._types import TypeResolver
from msxdbg.debuginfo.cdb_parser import parse_cdb
from msxdbg.debuginfo.model import Image, ImageId, ModuleId, TypeId
from msxdbg.debuginfo.index import Project
from msxdbg.eval.values import ValueDecoder, ValueLimits


FIXTURES = Path(__file__).parent / "fixtures" / "cdb"


def compiled_types():
    path = FIXTURES / "phase8_types.adb"
    parsed = parse_cdb(path.read_text().splitlines(), path)
    assert parsed.diagnostics == ()
    diagnostics = []
    image = ImageId("phase8")
    resolver = TypeResolver(image, parsed.value.types, diagnostics)
    types = resolver.finish()
    assert diagnostics == []
    return parsed.value, resolver, types, image


def test_real_sdcc_decimal_array_suffix_and_nested_layout_resolve():
    parsed, resolver, types, image = compiled_types()
    by_name = {item.name: item for item in types if item.category != "incomplete"}
    point = by_name["__00000000"]
    container = by_name["__00000001"]
    assert point.size == 3
    assert container.size == 10
    points = next(item for item in types if item.id == container.fields[0].type_id)
    assert points.category == "array" and points.array_count == 2 and points.size == 6
    assert resolver.chain(
        next(item for item in parsed.symbols if item.identity.name == "phase8_words").type_chain,
        ModuleId(image, "phase8_types"),
        next(item for item in parsed.symbols if item.identity.name == "phase8_words").origin,
    ).array_count == 3


def test_sdcc_4_6_z80_float_evidence_matches_explicit_f32_decoder():
    evidence = json.loads((FIXTURES / "phase8_float_abi.json").read_text())
    decoder = ValueDecoder(); project = Project((Image(ImageId("phase8")),))
    expected = (0.0, 1.0, -2.5)
    for case, value in zip(evidence["values"], expected):
        decoded = decoder.decode(bytes.fromhex(case["bytes"]),
                                 project.type_by_id(TypeId("f32")),
                                 project, ValueLimits())
        assert decoded.value == value


def test_compiled_cdb_float_chain_resolves_to_four_byte_f32():
    parsed, resolver, _, image = compiled_types()
    variable = next(item for item in parsed.symbols
                    if item.identity.name == "phase8_float_negative")
    type_ = resolver.chain(variable.type_chain,
                           ModuleId(image, "phase8_types"), variable.origin)
    assert type_.category == "float" and type_.size == 4
