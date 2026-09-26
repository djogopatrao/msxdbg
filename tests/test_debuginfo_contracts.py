"""Contract tests for the foundational offline debug-information DTOs."""

from dataclasses import FrozenInstanceError
from pathlib import Path
import unittest

from msxdbg.debuginfo.diagnostics import (
    Diagnostic,
    Origin,
    ParseResult,
    ProjectLoadError,
)
from msxdbg.debuginfo.model import (
    AddressRange,
    Image,
    ImageId,
    ModuleId,
    RegisterStorage,
    Resolution,
    ResolutionStatus,
    UnknownStorage,
)


class DiagnosticContractTests(unittest.TestCase):
    def test_parse_result_preserves_value_and_freezes_diagnostics(self) -> None:
        origin = Origin(Path("program.map"), 3, "symbol")
        diagnostic = Diagnostic("map.bad-record", "warning", "bad record", [origin])
        result = ParseResult(value=("valid",), diagnostics=[diagnostic])

        self.assertEqual(("valid",), result.value)
        self.assertEqual((diagnostic,), result.diagnostics)
        self.assertEqual((origin,), diagnostic.origins)
        with self.assertRaises(FrozenInstanceError):
            result.diagnostics = ()  # type: ignore[misc]

    def test_project_load_error_keeps_all_diagnostics(self) -> None:
        diagnostic = Diagnostic("load.failed", "error", "cannot load")
        error = ProjectLoadError("project is unusable", [diagnostic])

        self.assertEqual("project is unusable", str(error))
        self.assertEqual((diagnostic,), error.diagnostics)


class ModelContractTests(unittest.TestCase):
    def test_address_range_is_half_open_and_non_wrapping(self) -> None:
        low = AddressRange(0, 1)
        high = AddressRange(0xFFFF, 0x10000)

        self.assertTrue(low.contains(0))
        self.assertFalse(low.contains(1))
        self.assertTrue(high.contains(0xFFFF))
        with self.assertRaises(ValueError):
            AddressRange(10, 10)
        with self.assertRaises(ValueError):
            AddressRange(-1, 1)
        with self.assertRaises(ValueError):
            AddressRange(0xFFFF, 0x10001)

    def test_composite_identities_do_not_collapse_equal_names(self) -> None:
        first = ModuleId(ImageId("resident"), "main")
        second = ModuleId(ImageId("overlay"), "main")

        self.assertNotEqual(first, second)
        self.assertEqual(first, ModuleId(ImageId("resident"), "main"))

    def test_resolution_enforces_status_cardinality(self) -> None:
        unique = Resolution(ResolutionStatus.UNIQUE, [42])
        missing = Resolution(ResolutionStatus.MISSING)
        ambiguous = Resolution(ResolutionStatus.AMBIGUOUS, [1, 2])

        self.assertEqual(42, unique.unique_or_none())
        self.assertIsNone(missing.unique_or_none())
        self.assertIsNone(ambiguous.unique_or_none())
        self.assertEqual((1, 2), ambiguous.candidates)
        with self.assertRaises(ValueError):
            Resolution(ResolutionStatus.UNIQUE)
        with self.assertRaises(ValueError):
            Resolution(ResolutionStatus.AMBIGUOUS, [1])

    def test_storage_and_image_collections_are_immutable_tuples(self) -> None:
        storage = RegisterStorage(["L", "H"])
        image = Image(ImageId("resident"), diagnostics=[])

        self.assertEqual(("L", "H"), storage.registers)
        self.assertEqual((), image.diagnostics)
        with self.assertRaises(ValueError):
            UnknownStorage("")


if __name__ == "__main__":
    unittest.main()
