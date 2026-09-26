# Auditoria contratual dos stubs do msxdbg

Data: 26/09/2026  
Referência principal: `MODULE_DESIGN.md`  
Escopo: inventário e comparação estrutural. O primeiro lote de correção foi
aplicado depois da auditoria e está identificado abaixo.

## Resultado geral

O pacote compila e seus módulos podem ser importados, mas ainda não representa o
esqueleto público definido em `MODULE_DESIGN.md`.

- Os 39 nomes de classes dos blocos Python existem no código.
- As 16 funções de módulo dos blocos Python existem no código.
- Todos os módulos estruturais indicados pelo desenho estão presentes.
- Não restam retornos fictícios nas camadas estruturadas até aqui.
- Não foram encontrados imports entre camadas que violem a direção arquitetural.
  Isso ocorre principalmente porque quase não há colaboração entre módulos ainda.

Os números acima consideram somente os blocos Python do documento. Tipos
descritos em tabelas, como DTOs de modelo e resultados, aumentam
consideravelmente a lacuna real.

## Lote 1 concluído — fundamentos de `debuginfo`

Foram corrigidos `debuginfo/diagnostics.py` e `debuginfo/model.py`:

- `Diagnostic`, `ParseResult[T]` e `ProjectLoadError` agora preservam
  diagnósticos e origens em tuplas;
- identidades compostas, DTOs offline e variantes de `Storage` foram declarados
  como dataclasses imutáveis;
- `AddressRange` valida o domínio de 16 bits e rejeita intervalo vazio, inversão
  e wrap;
- `Resolution[T]` preserva status, candidatos e diagnósticos e valida a
  cardinalidade de `unique`, `missing` e `ambiguous`;
- `CodeLocation` foi movido para `debuginfo.model` e `session.state` passou a
  importá-lo;
- a sintaxe de união de `session/state.py` foi ajustada para Python 3.9.

Seis testes de contrato cobrem D01–D05 parcialmente. As seções abaixo mantêm o
registro dos demais problemas; os dois blocos marcados como resolvidos não são
mais pendências.

## Lote 2 concluído — contratos offline

Foram declarados:

- DTOs e assinaturas de `map_parser`, `lst_parser`, `cdb_parser` e
  `header_parser`;
- `ImageSpec`, `ProjectSpec`, `ImageArtifacts`, `LoadedProject`,
  `ProjectLoader` e `read_project_spec`;
- fachada `Project` e DTOs de consulta do índice;
- `SourceRepository` e `SourceWindow`;
- definições, contexto e catálogo de macros em `debuginfo/macros.py`.

Operações não implementadas lançam `NotImplementedError`. Quatro testes
estruturais adicionais verificam tuplas imutáveis, distinção de macro de objeto
e função e ausência de retornos fictícios.

## Lote 3 concluído — contratos do target

Foram separados `target/api.py`, `target/transport.py`, `target/openmsx.py` e
`target/fake.py`. DTOs, erros com resultado incerto, protocolo `Target`, transporte
e os dois adaptadores estão declarados. Nenhuma operação conecta ao openMSX;
stubs concretos lançam `NotImplementedError`.

## Lote 4 concluído — contratos da sessão

Foram declarados estado, resultados, execução, breakpoints, frames, segurança,
mapa de memória e a fachada `Session`. Operações ainda não implementadas falham
explicitamente. DTOs distinguem ausência, endereço zero e resultados desconhecidos.

## Lote 5 concluído — contratos de avaliação

Tokens, AST imutável, parser, macros, valores decodificados e `Evaluator` estão
declarados nos módulos previstos. O antigo `macro_expansions.py` foi removido.
Operações funcionais permanecem como stubs explícitos.

## Lote 6 concluído — UI e composição

Resultados, registro, dispatcher, handlers, REPL, batch, renderizadores e
`msxdbg.__main__` estão declarados. Importar a entrada CLI não executa trabalho;
operações ainda não implementadas falham explicitamente.

## P0 — Bloqueios fundamentais

### Módulos obrigatórios ausentes

Nenhum módulo estrutural listado em `MODULE_DESIGN.md` permanece ausente.

O antigo `eval/macro_expansions.py` foi substituído pelo contrato correto em
`eval/macros.py` no lote 5.

### `debuginfo/diagnostics.py` — resolvido no lote 1

Os quatro contratos fundamentais estão declarados. Os parsers ainda precisam
adotar `ParseResult` em seus próprios lotes.

### `debuginfo/model.py` — resolvido no lote 1

Os tipos fundamentais listados no desenho estão declarados, suas coleções são
normalizadas para tuplas e as invariantes estruturais demonstráveis são
validadas. Validação de ciclos de composição de tipos continua pertencendo ao
loader, não a estes DTOs.

### `target/api.py` — resolvido estruturalmente no lote 3

O módulo contém os DTOs e o protocolo tipado da camada:

- `RegisterSet`, `Instruction`, `PageState`, `RemoteBreakpoint`,
  `ExecutionStatus` e `TargetCapabilities`;
- `Target(Protocol)` com as 18 operações tipadas documentadas;
- `TargetError`, `TargetUnavailable`, `TargetTimeout`, `TargetCommandError` e
  `TargetProtocolError`.

`OpenMSXTarget` está em `target/openmsx.py`; transporte e `FakeTarget` também
possuem módulos próprios. Implementação funcional permanece pendente.

### `session/results.py` e `session/state.py` — resolvido estruturalmente no lote 4

Os resultados, configuração, snapshot, seleção, cache, assinatura e protocolo de
inspeção estão declarados. A duplicata antiga de `LocationResult` foi removida no
lote de avaliação.

## P1 — Contratos ausentes ou incompatíveis por camada

### Parsers de `debuginfo` — resolvido estruturalmente no lote 2

| Arquivo | Contrato | Estado atual |
| --- | --- | --- |
| `map_parser.py` | `ParseResult[MapData]` | assinatura declarada; stub explícito |
| `lst_parser.py` | `ParseResult[ListingData]` | assinatura declarada; stub explícito |
| `cdb_parser.py` | `ParseResult[CdbData]` | assinatura declarada; stub explícito |
| `header_parser.py` | `parse_headers(Sequence[HeaderInput]) -> ParseResult[HeaderTypes]` | assinatura declarada; stub explícito |

Os DTOs públicos estão presentes. A implementação funcional dos parsers continua
pendente e pertence a uma etapa posterior.

### Loader, índice, fontes e macros — resolvido estruturalmente no lote 2

Os tipos e métodos públicos desta seção estão declarados com coleções em tuplas.
Descoberta, carregamento, consultas, leitura de fontes e resolução de macros
continuam como stubs explícitos.

### Transporte e alvo falso — resolvido estruturalmente no lote 3

DTOs, transporte, descoberta de socket, adaptador e alvo falso estão declarados.
As operações concretas continuam explicitamente não implementadas.

### Sessão — resolvida estruturalmente no lote 4

Os módulos e contratos públicos desta camada estão declarados. Máquina de
estados, execução, frames, segurança e gerenciamento de breakpoints permanecem
sem comportamento funcional.

### Avaliação — resolvida estruturalmente no lote 5

Os tipos e fachadas desta camada estão declarados. Tokenização, parsing,
expansão, decodificação e avaliação funcional permanecem pendentes.

### UI e composição — resolvidas estruturalmente no lote 6

Os contratos de resultados, registro, comandos, runners, renderizadores e CLI
estão presentes. Comportamento funcional continua pendente.

## P2 — Qualidade estrutural e compatibilidade

### Retornos fictícios e falhas silenciosas

Não restam retornos de sucesso fictício conhecidos. Classes base e exceções com
corpo vazio não simulam resultado operacional.

As exceções vazias `MsxdbgError` e `ParseError` não são por si só retornos
fictícios, mas `ParseError` também não possui os campos de diagnóstico necessários
para substituir `ProjectLoadError`.

### DTOs mutáveis ou incompletos

Não restam pendências estruturais conhecidas nesta categoria. DTOs usam tuplas ou
cópias somente de leitura nas coleções expostas.

### Python 3.9

Todos os arquivos atuais do pacote passam em
`ast.parse(..., feature_version=(3, 9))`.
O runtime Python 3.9 não está disponível neste ambiente; portanto, execução real
nessa versão continua não verificada.

### Dependências e imports

Não há hoje imports proibidos entre camadas. `debuginfo` e `target` usam apenas a
biblioteca padrão; `session` não importa `eval` ou `ui`; e `ui` não acessa o
target. Também não há I/O ou conexão executados durante import.

Esse resultado não valida a arquitetura futura: várias dependências necessárias
ainda não foram declaradas, e nomes usados em anotações, como `StopSnapshot` em
`session/core.py`, não resolvem por introspecção de tipos.

## Ordem recomendada de correção

Cada lote deve atualizar ou criar apenas os arquivos indicados, executar
`VALIDATE_STUBS.py` e receber testes estruturais próprios antes do commit.

1. **Concluído:** `debuginfo/diagnostics.py` e `debuginfo/model.py`.
2. **Concluído:** parsers, `loader.py`, `index.py`, `sources.py` e
   `debuginfo/macros.py`.
3. `target/api.py`: declarar DTOs, erros e `Target(Protocol)`; depois criar
   separadamente `transport.py`, `openmsx.py` e corrigir `fake.py`.
4. `session/results.py` e `state.py`; depois `execution.py`, `breakpoints.py`,
   `frames.py`, `safety.py`, `memory_map.py` e `core.py`.
5. **Concluído:** `eval/tokens.py`, `ast.py`, `parser.py`, `values.py`,
   `macros.py` e `evaluator.py`.
6. **Concluído:** contratos de `ui` e `msxdbg/__main__.py`.

Esta ordem reflete as dependências unidirecionais do desenho e evita criar tipos
duplicados em camadas superiores.

## Evidência da auditoria

Foram usados:

- inventário AST de todos os arquivos em `msxdbg/`;
- inventário AST dos blocos Python de `MODULE_DESIGN.md`;
- busca por `pass`, `...`, retornos vazios e imports;
- `python3 -B VALIDATE_STUBS.py` para confirmar que a base continua importável.

O relatório não afirma cobertura funcional. Ele registra as diferenças entre o
desenho e o código na data acima.
