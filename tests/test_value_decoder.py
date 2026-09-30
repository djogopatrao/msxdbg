"""Pure typed-value decoding tests."""

import math
import struct

import pytest

from msxdbg.debuginfo.index import Project
from msxdbg.debuginfo.model import (AbsoluteStorage, Field, Image, ImageId,
    ModuleId, ResolutionStatus, TypeDef, TypeId, Variable, VariableId)
from msxdbg.eval.values import (ArrayValue, ScalarValue, StringValue,
    StructValue, ValueDecoder, ValueLimits, default_print_type)


decoder = ValueDecoder()
limits = ValueLimits()
empty = Project(())


@pytest.mark.parametrize("name,data,expected", [
    ("u8", b"\xff", 255), ("i8", b"\x80", -128),
    ("u16", b"\x34\x12", 0x1234), ("i16", b"\x00\x80", -32768),
    ("u32", b"\x78\x56\x34\x12", 0x12345678),
    ("bool", b"\x02", True), ("ptr", b"\x00\x80", 0x8000),
])
def test_decode_scalar_little_endian(name, data, expected):
    type = empty.type_by_id(TypeId(name))
    value = decoder.decode(data, type, empty, limits)
    assert isinstance(value, ScalarValue)
    assert value.value == expected
    assert value.raw_bytes == data


def test_decode_float_and_nonfinite_without_emitting_nan_value():
    type = empty.type_by_id(TypeId("f32"))
    assert decoder.decode(struct.pack("<f", 1.5), type, empty, limits).value == 1.5
    special = decoder.decode(struct.pack("<f", math.inf), type, empty, limits)
    assert special.value == {"value": None, "classification": "+infinity"}


def typed_project(*types):
    return Project((Image(ImageId("app"), types=types),))


def test_decode_character_array_as_latin1_string():
    array = TypeDef(TypeId("chars"), "chars", "array", 5, False,
                    TypeId("c8"), array_count=5)
    project = typed_project(array)
    value = decoder.decode(b"ol\xe1\0x", array, project, limits)
    assert value == StringValue("olá", True, False, b"ol\xe1\0x")


def test_decode_array_honors_element_limit():
    array = TypeDef(TypeId("words"), "words", "array", 40, False,
                    TypeId("u16"), array_count=20)
    project = typed_project(array)
    value = decoder.decode(bytes(40), array, project, ValueLimits(max_elements=3))
    assert isinstance(value, ArrayValue)
    assert len(value.items) == 3
    assert value.truncated


def test_decode_struct_fields_from_one_local_buffer():
    struct_type = TypeDef(TypeId("pair"), "pair", "struct", 3,
                          fields=(Field("left", TypeId("u8"), 0),
                                  Field("right", TypeId("u16"), 1)))
    project = typed_project(struct_type)
    value = decoder.decode(b"\x07\x34\x12", struct_type, project, limits)
    assert isinstance(value, StructValue)
    assert [item.value for _, item in value.fields] == [7, 0x1234]


def test_decoder_rejects_short_incomplete_and_oversized_values():
    with pytest.raises(ValueError): decoder.decode(b"\x00", empty.type_by_id(TypeId("u16")), empty, limits)
    incomplete = TypeDef(TypeId("missing"), "missing", "incomplete")
    with pytest.raises(ValueError): decoder.decode(b"", incomplete, empty, limits)
    big = TypeDef(TypeId("big"), "big", "array", 5000, referenced_type=TypeId("u8"), array_count=5000)
    with pytest.raises(ValueError): decoder.decode(bytes(5000), big, typed_project(big), limits)


def test_default_print_type_accepts_scalar_and_rejects_pointer():
    image = ImageId("app"); module = ModuleId(image, "main")
    scalar = Variable(VariableId(module, "x"), "x", None, None, TypeId("u16"), AbsoluteStorage(0x100))
    pointer = Variable(VariableId(module, "p"), "p", None, None, TypeId("ptr"), AbsoluteStorage(0x102))
    assert default_print_type(scalar, empty).status == ResolutionStatus.UNIQUE
    assert default_print_type(pointer, empty).status == ResolutionStatus.MISSING
