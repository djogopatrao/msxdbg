"""Structural tests for the remaining offline debuginfo stubs."""

from pathlib import Path
import unittest

from msxdbg.debuginfo.cdb_parser import CdbData, parse_cdb
from msxdbg.debuginfo.diagnostics import Origin, ParseResult
from msxdbg.debuginfo.header_parser import HeaderInput, HeaderTypes, parse_headers
from msxdbg.debuginfo.index import CompletionCatalog, Project
from msxdbg.debuginfo.loader import ImageArtifacts, ImageSpec, ProjectSpec
from msxdbg.debuginfo.lst_parser import ListingData, parse_lst
from msxdbg.debuginfo.macros import (
    MacroCatalog,
    MacroContext,
    MacroDefinition,
    MacroToken,
    parse_macro_definitions,
)
from msxdbg.debuginfo.map_parser import MapData, parse_map
from msxdbg.debuginfo.model import ImageId
from msxdbg.debuginfo.sources import SourceRepository


class OfflineDtoTests(unittest.TestCase):
    def test_collections_are_normalized_to_tuples(self) -> None:
        image_id = ImageId("resident")
        image_spec = ImageSpec(image_id, Path("out"), maps=[Path("a.map")])
        project_spec = ProjectSpec([image_spec], [Path("src")])
        artifacts = ImageArtifacts(maps=[Path("a.map")])

        self.assertEqual((Path("a.map"),), image_spec.maps)
        self.assertEqual((image_spec,), project_spec.images)
        self.assertEqual((Path("src"),), project_spec.source_roots)
        self.assertEqual((Path("a.map"),), artifacts.maps)
        self.assertEqual((), MapData([]).symbols)
        self.assertEqual((), ListingData("main", areas=[]).areas)
        self.assertEqual((), CdbData(functions=[]).functions)
        self.assertEqual((), HeaderTypes(types=[]).types)
        self.assertEqual((), CompletionCatalog(symbols=[]).symbols)
        self.assertEqual((), Project([]).images)

    def test_macro_definition_preserves_parameter_distinction(self) -> None:
        origin = Origin(Path("config.h"), 1, "define")
        context = MacroContext(ImageId("resident"), "main.c")
        object_like = MacroDefinition(
            "LIMIT", None, [MacroToken("10")], origin, context
        )
        function_like = MacroDefinition("ZERO", [], [], origin, context)

        self.assertIsNone(object_like.parameters)
        self.assertEqual((), function_like.parameters)
        self.assertEqual((object_like,), MacroCatalog([object_like]).definitions)


class ExplicitStubFailureTests(unittest.TestCase):
    def test_parser_map_is_implemented(self) -> None:
        """parse_map foi implementado (primeiro marco funcional)."""
        # parse_map retorna ParseResult[MapData] ao invés de NotImplementedError
        origin = Path("input")
        result = parse_map([], origin)
        assert isinstance(result, ParseResult)
        assert not isinstance(result.value, type(None))

    def test_parse_lst_is_implemented(self) -> None:
        result = parse_lst([], Path("input.lst"))
        self.assertIsInstance(result, ParseResult)
        self.assertIsInstance(result.value, ListingData)
        self.assertEqual((), result.diagnostics)

    def test_parse_cdb_is_implemented(self) -> None:
        result = parse_cdb([], Path("input.cdb"))
        self.assertIsInstance(result, ParseResult)
        self.assertIsInstance(result.value, CdbData)
        self.assertEqual((), result.diagnostics)

    def test_other_parsers_fail_explicitly(self) -> None:
        """Outros parsers ainda são stubs que lançam NotImplementedError."""
        origin = Path("input")
        calls_list = [
            ("parse_headers", lambda: parse_headers([HeaderInput(origin, "")])),
            (
                "parse_macro_definitions",
                lambda: parse_macro_definitions("", origin, MacroContext()),
            ),
        ]

        for name, call in calls_list:
            with self.subTest(call=call):
                with self.assertRaises(NotImplementedError):
                    call()

    def test_map_result_structure(self) -> None:
        """Resultado de parse_map tem estrutura correta."""
        result = parse_map([], Path("test.map"))
        assert isinstance(result, ParseResult)
        assert hasattr(result, "value") and hasattr(result, "diagnostics")
        from msxdbg.debuginfo.map_parser import MapData
        assert isinstance(result.value, MapData)

    def test_services_fail_explicitly(self) -> None:
        sources = SourceRepository()
        catalog = MacroCatalog()

        with self.assertRaises(NotImplementedError):
            sources.invalidate()
        with self.assertRaises(NotImplementedError):
            catalog.names(MacroContext())


if __name__ == "__main__":
    unittest.main()
