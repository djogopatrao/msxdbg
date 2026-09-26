# Estado da recuperação do msxdbg

Data da verificação: 26/09/2026  
Raiz do projeto: `/home/djogo/Documentos/msxdbg`

## Situação por área

| Área | Estado | Evidência |
| --- | --- | --- |
| Estrutura do pacote | Aprovada | `msxdbg/` contém `debuginfo`, `target`, `session`, `eval` e `ui`, todos com `__init__.py` |
| `map_parser.py` | Recuperado | Origem e destino têm SHA-256 `b62df96a63634c4f64240f22dfe6a6073bcbbfe8a3bfa66e6861f9fecbfe425d` |
| Sintaxe e imports | Aprovados | 28 fontes passaram na sintaxe e 27 módulos passaram no import canônico |
| Recuperação documental | Completa | Os seis documentos do msxdbg estão presentes e foram identificados pelo conteúdo |
| Contratos e funcionalidades | Não avaliados | Esta recuperação cobre somente estrutura, sintaxe e imports |

## Backup e arquivo recuperado

Backup consultado: `/tmp/msxdbg_backup_20250926_091430/`

O arquivo `/tmp/msxdbg_backup_20250926_091430/map_parser.py` foi recuperado em
`msxdbg/debuginfo/map_parser.py`. A comparação SHA-256 confirma que o conteúdo é
idêntico ao backup.

## Documentação

Os seis documentos foram recuperados na raiz do projeto. Títulos, conteúdo e
referências cruzadas identificam as versões como pertencentes ao msxdbg:

| Documento | SHA-256 |
| --- | --- |
| `MODULE_DESIGN.md` | `cc4fd9498fb3da6c821123734586b6f0f7465cf2a2a2b68a2f7968cf6e67f112` |
| `ARCHITECTURE.md` | `681f1a42567779056e8c576dba18ab94c4e5afb18c8588c3e65d7cb24cd89335` |
| `COMMANDS.md` | `eb1f49a654434a1f92576c3c9b33079ae297762dd7f15e46f8fa7435b2d65813` |
| `SPEC.md` | `3158a19fe479b1457812d09c5a42093bf904b9cc326fbe89add4b234150296ab` |
| `BACKLOG.md` | `ce67d234d84d645f136ac68fd347c6c6e1a694dedc0a9be575697c1e86a2816d` |
| `TEST_PLAN.md` | `7cb9a3fd0b556783a02345b8aae11f5093da06df18f871bd651184ea4c82006e` |

A origem externa usada para recolocar esses arquivos não foi registrada neste
relatório. Os hashes acima estabelecem a versão atualmente validada.

## Validador

`VALIDATE_STUBS.py` usa somente a biblioteca padrão e:

- confere os arquivos obrigatórios do pacote;
- compila o próprio validador e todos os arquivos Python do pacote sem executá-los;
- converte os caminhos em nomes canônicos;
- importa cada módulo em um subprocesso separado, com `cwd` na raiz e timeout de
  10 segundos;
- retorna código 1 se qualquer verificação falhar.

O validador não modifica `sys.path` ou `PYTHONPATH`, não depende de `__pycache__`
e não executa a CLI do debugger.

## Comandos de validação

```bash
python3 -B VALIDATE_STUBS.py
python3 -B -c "import msxdbg.debuginfo.map_parser; import msxdbg.target; import msxdbg.session; import msxdbg.eval; import msxdbg.ui"
python3 -B -c "import ast; print(ast.__file__); assert hasattr(ast, 'Add')"
```

Resultados observados:

- `python3 -B VALIDATE_STUBS.py` — código 0; 28 verificações de sintaxe
  aprovadas, 27 imports aprovados, zero falhas e zero arquivos obrigatórios
  ausentes.
- Import conjunto dos cinco subpacotes e de `msxdbg.debuginfo.map_parser` —
  código 0.
- Verificação da biblioteca padrão `ast` — código 0; carregou
  `/usr/lib/python3.14/ast.py` e encontrou `ast.Add`.

## Resultado final

Estrutura, sintaxe e imports: APROVADOS.  
Recuperação documental: COMPLETA.  
Contratos e funcionalidades: NÃO AVALIADOS.

Esta etapa verifica estrutura, sintaxe e imports. Não comprova conformidade dos
contratos nem funcionamento do debugger.
