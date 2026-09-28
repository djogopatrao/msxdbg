"""Structural tests for UI and CLI stubs."""
import importlib
import unittest
from msxdbg.ui.commands import CommandDispatcher, build_registry, parse_target
from msxdbg.ui.registry import CommandRegistry
from msxdbg.ui.results import CommandError, CommandResult

class UiContractTests(unittest.TestCase):
    def test_command_result_enforces_success_error_invariant(self) -> None:
        self.assertTrue(CommandResult("help", True).ok)
        error = CommandError("bad", "bad command", {})
        self.assertFalse(CommandResult("bad", False, error=error).ok)
        with self.assertRaises(ValueError): CommandResult("bad", False)

    def test_ui_operations_fail_explicitly(self) -> None:
        with self.assertRaises(NotImplementedError): build_registry()
        with self.assertRaises(NotImplementedError): parse_target("main")
        with self.assertRaises(NotImplementedError): CommandRegistry().specifications()

    def test_cli_module_import_has_no_execution(self) -> None:
        module = importlib.import_module("msxdbg.__main__")
        self.assertTrue(callable(module.main))

if __name__ == "__main__": unittest.main()
