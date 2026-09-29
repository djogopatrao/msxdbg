"""Structural tests for offline debuginfo contracts."""

from pathlib import Path
import unittest

from msxdbg.debuginfo.cdb_parser import CdbData, parse_cdb
from msxdbg.debuginfo.diagnostics import Origin, ParseResult
from msxdbg.debuginfo.header_parser import HeaderInput, HeaderTypes, parse_headers
from msxdbg.debuginfo.index import CompletionCatalog, Project
from msxdbg.debuginfo.loader import ImageArtifacts, ImageSpec, ProjectSpec
from msxdbg.debuginfo.lst_parser import ListingData, parse_lst
from msxdbg.debuginfo.macros import MacroCatalog, MacroContext, MacroDefinition, MacroToken, parse_macro_definitions
from msxdbg.debuginfo.map_parser import MapData, parse_map
from msxdbg.debuginfo.model import ImageId
from msxdbg.debuginfo.sources import SourceRepository


class OfflineDtoTests(unittest.TestCase):
    def test_collections_are_normalized_to_tuples(self) -> None:
        image_spec = ImageSpec(ImageId("resident"), Path("out"), maps=[Path("a.map")])
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
        object_like = MacroDefinition("LIMIT", None, [MacroToken("10")], origin, context)
        function_like = MacroDefinition("ZERO", [], [], origin, context)
        self.assertIsNone(object_like.parameters)
        self.assertEqual((), function_like.parameters)
        self.assertEqual((object_like,), MacroCatalog([object_like]).definitions)


class ParserContractTests(unittest.TestCase):
    def test_parser_map_is_implemented(self) -> None:
        result = parse_map([], Path("input"))
        self.assertIsInstance(result, ParseResult)
        self.assertIsInstance(result.value, MapData)

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

    def test_remaining_parsers_fail_explicitly(self) -> None:
        origin = Path("input")
        calls = (lambda: parse_headers([HeaderInput(origin, "")]),)
        for call in calls:
            with self.subTest(call=call):
                with self.assertRaises(NotImplementedError):
                    call()

    def test_services_fail_explicitly(self) -> None:
        with self.assertRaises(NotImplementedError):
            SourceRepository().invalidate()
        self.assertEqual((), MacroCatalog().names(MacroContext()))
