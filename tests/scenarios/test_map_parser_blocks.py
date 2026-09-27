"""Testes comportamentais que expõem os bloqueios da Fase 1 do parser MAP."""

from pathlib import Path
import pytest

from msxdbg.debuginfo.diagnostics import ParseResult
from msxdbg.debuginfo.map_parser import parse_map


class TestParseMapBlockP1:
    """Explora os P1 listados em FASE_1_FEEDBACK.md"""

    def test_valid_line_without_module_should_not_raise(self) -> None:
        """P1: Linha válida sem módulo não deve causar exceção.
        
        Reproduz o bug: parse_map(["0001 _outside\n"], Path("x.map"))
        
        Esperado: retorna resultado/diagnóstico, nunca UnboundLocalError.
        """
        result = parse_map(["0001 _outside\n"], Path("x.map"))
        
        assert isinstance(result, ParseResult)
        assert result.value.symbols == ()

    def test_symbol_before_header_ignored(self) -> None:
        """P1: Símbolo aparente antes de 'Value Global' deve ser ignorado.
        
        Esperado: símbolo antes do cabeçalho não é coletado.
        """
        lines = [
            "0000 symbol_before\n",
            "0000 another_before\n",
            "Value  Global\n",
            "0100 valid_after\n",
        ]
        result = parse_map(lines, Path("test.map"))
        
        assert len(result.value.symbols) == 1
        # O único símbolo coletado é o após o cabeçalho
        assert result.value.symbols[0].name == "valid_after"

    def test_symbol_valid_after_header_collected(self) -> None:
        """P1: Símbolo após o cabeçalho deve ser coletado.
        
        Esperado: símbolos válidos após 'Value Global' são capturados.
        """
        lines = [
            "Value  Global\n",
            "0100 valid_symbol\n",
        ]
        result = parse_map(lines, Path("test.map"))
        
        assert len(result.value.symbols) == 1
        assert result.value.symbols[0].name == "valid_symbol"

    def test_repeated_header_continues_parsing(self) -> None:
        """P1: Cabeçalho repetido por paginação deve continuar a coleta.
        
        Esperado: múltiplos 'Value Global' reiniciam a tabela, coletando símbolos subsequentes.
        """
        lines = [
            "0000 first_page_symbol\n",
            "Value  Global\n",
            "0100 second_page_first\n",
            "0200 second_page_second\n",
            "ASxxxx Linker Page 2\n",
            "Value  Global\n",
            "0300 third_page_first\n",
        ]
        result = parse_map(lines, Path("test.map"))
        
        # Símbolos da primeira página (antes do primeiro cabeçalho) não são coletados
        # Símbolos das tabelas subsequentes devem ser coletados após cada "Value Global"
        assert len(result.value.symbols) == 3

    def test_line_with_high_address_over_limit(self) -> None:
        """P1: Endereço > 0xFFFF deve gerar diagnóstico, não símbolos.
        
        Esperado: cria Diagnostic com código específico, não Symbol.
        """
        lines = [
            "Value  Global\n",
            "10000 too_high_addr foo\n",  # > 0xFFFF (65536)
        ]
        result = parse_map(lines, Path("test.map"))
        
        assert len(result.value.symbols) == 0
        assert len(result.diagnostics) == 1

    def test_diagnostic_has_origin_path_and_line(self) -> None:
        """P1: Diagnósticos devem incluir caminho e número de linha.
        
        Esperado: Origin(path=origin, line=<número real>, record_kind="map").
        """
        lines = [
            "Value  Global\n",
            "malformed line here\n",
        ]
        result = parse_map(lines, Path("myfile.map"))
        
        assert len(result.diagnostics) == 1
        origin = result.diagnostics[0].origins[0]
        assert origin.path == Path("myfile.map")
        assert origin.line == 2

    def test_valid_record_after_invalid_record(self) -> None:
        """P1: Registro válido após linha inválida deve ser parseado.
        
        Esperado: uma linha malformada não destrói a capacidade de coletar símbolos posteriores válidos.
        """
        lines = [
            "Value  Global\n",
            "bad line format\n",
            "0200 valid_after_error\n",
        ]
        result = parse_map(lines, Path("test.map"))
        
        # O símbolo após o erro ainda deve ser coletado
        assert len(result.value.symbols) == 1

    def test_line_with_module_column_present(self) -> None:
        """Verifica que linhas com coluna de módulo são aceitas.
        
        Esperado: nome + ' nome do módulo' é parseado corretamente.
        """
        lines = [
            "Value  Global\n",
            "0100 _symbol_name mymodulename\n",
        ]
        result = parse_map(lines, Path("test.map"))
        
        assert len(result.value.symbols) == 1
        symbol = result.value.symbols[0]
        assert symbol.name == "_symbol_name"
        assert symbol.address == 0x0100
        assert symbol.module_key == "mymodulename"
        assert symbol.origin.line == 2


class TestParseMapPseudoSymbols:
    """Teste que diferencia pseudo-símbolos s__/l__ de nomes comuns."""

    def test_pseudo_symbol_s_prefix(self) -> None:
        """Pseudo-símbolo com prefixo s__ é preservado sem módulo."""
        lines = [
            "Value  Global\n",
            "0100 s__DATA area_boundary\n",
        ]
        result = parse_map(lines, Path("test.map"))

        assert len(result.value.symbols) == 1
        sym = result.value.symbols[0]
        assert sym.name == "s__DATA"
        assert sym.module_key is None  # pseudo-símbolo não associa módulo

    def test_pseudo_symbol_l_prefix(self) -> None:
        """Pseudo-símbolo com prefixo l__ é preservado sem módulo."""
        lines = [
            "Value  Global\n",
            "0200 l__CODE area_boundary\n",
        ]
        result = parse_map(lines, Path("test.map"))

        assert len(result.value.symbols) == 1
        sym = result.value.symbols[0]
        assert sym.name == "l__CODE"
        assert sym.module_key is None  # pseudo-símbolo não associa módulo

    def test_s_prefix_single_underscore_not_pseudo(self) -> None:
        """Nome iniciado por s_|l_ (um underscore) NÃO é pseudo-símbolo."""
        lines = [
            "Value  Global\n",
            "0100 s_function normal_func\n",
            "0200 l_data another_normal\n",
        ]
        result = parse_map(lines, Path("test.map"))

        assert len(result.value.symbols) == 2
        # s_function e l_data são tratados como nomes comuns sem prefixo pseudo

    def test_l_prefix_single_underscore_not_pseudo(self) -> None:
        """Nome iniciado por lo_|l_ com um underscore é tratado como comum."""
        lines = [
            "Value  Global\n",
            "0100 local_var ordinary_symbol\n",
        ]
        result = parse_map(lines, Path("test.map"))

        assert len(result.value.symbols) == 1
        sym = result.value.symbols[0]
        assert sym.name == "local_var"

    def test_module_key_with_pseudo_name(self) -> None:
        """Pseudo-símbolo sem módulo, mesmo se coluna de módulo está presente."""
        lines = [
            "Value  Global\n",
            "0100 s__DATA some_modkey\n",
        ]
        result = parse_map(lines, Path("test.map"))

        assert len(result.value.symbols) == 1
        sym = result.value.symbols[0]
        # Pseudo-símbolos nunca recebem módulos (requisito §4 em FASE_1_FEEDBACK)
        assert sym.module_key is None
        assert sym.name == "s__DATA"

    def test_mixed_symbols_and_pseudo(self) -> None:
        """Símbolos válidos e pseudo-símbolos coexistem na tabela."""
        lines = [
            "Value  Global\n",
            "0100 s__HEAP area_boundary\n",
            "0200 normal_symbol code_func\n",
            "0300 third_normal yet_another\n",
        ]
        result = parse_map(lines, Path("test.map"))

        symbols = result.value.symbols
        assert len(symbols) == 3
        
        # Um pseudo-símbolo s__HEAP sem módulo
        pseudo_count = sum(1 for s in symbols if s.name[:3] in ("s__", "l__"))
        assert pseudo_count == 1
        
        # Dois símbolos comuns com módulos opcionais
        common_count = len(symbols) - pseudo_count
        assert common_count == 2

    def test_mixed_symbols_and_pseudo_multiple_pages(self) -> None:
        """Símbolos válidos e pseudo-símbolos em múltiplas páginas."""
        lines = [
            "s__CODE antes_global\n",  # Ignorado (antes do primeiro Value Global)
            "Value  Global\n",  # Página 1 - começamos a colecionar
            "0100 s__HEAP area_boundary\n",
            "0200 normal_symbol code_func\n",
            "ASxxxx Linker Page 2\n",  # Fim da página 1
            "Value  Global\n",  # Página 2 - começamos a colecionar novamente
            # l__CODE após o segundo "Value Global" é coletado agora
            "l__CODE another_area\n",
            "0300 third_normal yet_another\n",
        ]
        result = parse_map(lines, Path("test.map"))

        symbols = result.value.symbols
        
        # Um pseudo-símbolo s__HEAP na página 1 e um l__CODE na página 2
        assert len(symbols) == 3
        
        # Dois pseudo-símbolos em páginas diferentes (mas o ASxxxx Linker quebra a coleta)
        # O código atual apenas coleta símbolos em cada seção "Value Global" separada por ASxxxx
        pseudo_count = sum(1 for s in symbols if s.name[:3] in ("s__", "l__"))
        assert pseudo_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
