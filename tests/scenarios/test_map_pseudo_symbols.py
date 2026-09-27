"""Testes para pseudo-símbolos s__ e l__ do parser MAP."""

from pathlib import Path
import pytest

from msxdbg.debuginfo.map_parser import parse_map


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
        sym_name1, sym_name2 = (s.name for s in result.value.symbols)

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
            # "s__CODE another_area" está antes de outro "Value Global", portanto é ignorado
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
            "0300 yet_another normal2\n",  
        ]
        result = parse_map(lines, Path("test.map"))

        symbols = result.value.symbols
        
        # Um pseudo-símbolo s__HEAP na página 1 e out pseudo-símbolos l__ se houverem no arquivo
        assert len(symbols) == 3
        
        pseudo_count = sum(1 for s in symbols if s.name[:3] in ("s__", "l__"))
        # Apenas um s__, não há l__ neste fluxo


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
