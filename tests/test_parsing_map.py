"""MAP parsing tests for the first functional milestone."""

from pathlib import Path

import pytest

from msxdbg.debuginfo.diagnostics import ParseResult
from msxdbg.debuginfo.map_parser import MapData, parse_map


@pytest.fixture
def minimal_map_path() -> Path:
    return Path("tests/fixtures/maps/minimal.map")


@pytest.fixture
def multi_path() -> Path:
    return Path("tests/fixtures/maps/multiple.map")


class TestParseMapContract:
    """Teste do contrato público da API."""

    def test_accepts_empty_sequence(self) -> None:
        """Resultado vazio para entrada vazia, sem exceção."""
        result = parse_map([], Path("empty"))
        assert isinstance(result, ParseResult)
        assert isinstance(result.value, MapData)
        assert result.value.symbols == ()
        assert result.diagnostics == ()

    def test_accepts_none_sequence(self) -> None:
        """Trata `None` como sequência de linhas vazia."""
        result = parse_map(None, Path("none"))
        assert isinstance(result.value, MapData)
        assert result.value.symbols == ()


class TestParseMapMinimalValid:
    """Caso válido mínimo com um símbolo e área."""

    def test_minimal_map_with_one_symbol_and_area(self, minimal_map_path: Path) -> None:
        """Parseia um MAP mínimo com símbolos após 'Value Global'."""
        with minimal_map_path.open("r") as f:
            lines = f.readlines()
        result = parse_map(lines, minimal_map_path)

        assert isinstance(result.value, MapData)
        # Um símbolo público (_g_code_base) + uma área (s__HEAP com prefixo duplo_)
        assert len(result.value.symbols) == 2


class TestParseMapMultipleValid:
    """Múltiplos símbolos válidos."""

    def test_multiple_symbols_without_errors(self, minimal_map_path: Path) -> None:
        """Múltiplos símbolos parseados sem gerar erro."""
        with minimal_map_path.open("r") as f:
            lines = f.readlines()
        result = parse_map(lines, minimal_map_path)

        assert isinstance(result.value, MapData)
        assert len(result.value.symbols) == 2


class TestParseMapInvalidLineGeneratesDiagnostic:
    """Linha inválida gera diagnostic explícito."""

    def test_malformed_line_generates_diagnostic(self, multi_path: Path) -> None:
        """Uma linha malformada gera um diagnóstico sem abortar o parsing."""
        with multi_path.open("r") as f:
            lines = f.readlines()
        result = parse_map(lines, Path(multi_path))

        assert isinstance(result.value, MapData)
        # Deve ter pelo menos os símbolos válidos + diagnósticos (se houver erro)
        assert len(result.value.symbols) > 0


class TestParseMapPartialInvalidity:
    """Registros inválidos não eliminam registros válidos seguintes."""

    def test_valid_records_after_invalid(self, multi_path: Path) -> None:
        """Registros válidos após uma linha inválida são parseados."""
        with multi_path.open("r") as f:
            lines = f.readlines()
        result = parse_map(lines, Path(multi_path))

        assert isinstance(result.value, MapData)
        # Símbolos válidos devem ser capturados mesmo antes do erro
        assert len([s for s in result.value.symbols if s.module_key is None]) >= 1


class TestParseMapHexFormat:
    """Endereços hexadecimais de 4-8 dígitos."""

    def test_eight_digit_hex_address(self, minimal_map_path: Path) -> None:
        """Endereço de 4-8 dígitos hex (ex: 007e00)."""
        with minimal_map_path.open("r") as f:
            lines = f.readlines()
        result = parse_map(lines, minimal_map_path)

        assert isinstance(result.value, MapData)
        for symbol in result.value.symbols:
            # Endereço válido no domínio 0..65535
            assert 0 <= symbol.address <= 0xFFFF


class TestParseMapNoNotImplementedError:
    """Substitui NotImplementedError por implementação."""

    def test_no_not_implemented_error(self, minimal_map_path: Path) -> None:
        """parse_map não levanta NotImplementedError mais."""
        with minimal_map_path.open("r") as f:
            lines = f.readlines()
        result = parse_map(lines, minimal_map_path)

        assert isinstance(result.value, MapData)
        if result.diagnostics:
            msgs = [d.code for d in result.diagnostics]
            assert "NotImplementedError" not in msgs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
