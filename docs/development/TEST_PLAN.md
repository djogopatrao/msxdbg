# msxdbg — Plano de testes por módulo e função

Base: [MODULE_DESIGN.md](MODULE_DESIGN.md), [COMMANDS.md](../../COMMANDS.md), [ARCHITECTURE.md](ARCHITECTURE.md), [BACKLOG.md](BACKLOG.md) e o comportamento histórico explicitamente preservado de [SPEC.md](SPEC.md).

Este documento planeja e rastreia testes; resultados de execução pertencem ao CI ou à revisão da mudança. O repositório contém contratos estruturais e o primeiro incremento funcional, `parse_map`, com fixtures sintéticas de MAP. Os demais componentes podem continuar como stubs até seus incrementos próprios. As regras F17/F18 prevalecem sobre print legado onde diferem. Funções repetidas no desenho são um único contrato; métodos de Protocol são testados pelas implementações e pelos consumidores, não pela instanciação do protocolo.

## 1. Estratégia e critérios gerais

Adotar pytest como ferramenta de desenvolvimento, com testes parametrizados. Usar biblioteca padrão para servidor de socket falso, arquivos temporários e validação JSON. Property-based testing é opcional, somente quando agregar exploração de fronteiras além dos exemplos determinísticos.

| Nível | Objetivo | Quando habilitar |
| --- | --- | --- |
| S — estrutura | Imports, assinaturas, dependências e falha explícita dos stubs | Assim que existirem stubs |
| U — unidade | Contrato de uma função, dados e erros observáveis | Ao implementar a função |
| C — contrato | Mesma API sob FakeTarget e adaptador com transporte controlado | Ao implementar Target |
| I — integração local | Colaboração de componentes com arquivos reais e alvo falso | Por incremento funcional |
| G — golden | Texto e JSON estáveis de comandos | Depois de estabilizar apresentação |
| L — live opt-in | Validar hipóteses do protocolo/ABI em ambiente preparado | Somente com ambiente explicitamente disponibilizado |

Não aprovar uma funcionalidade apenas porque seu stub lança NotImplementedError. Testes funcionais não devem passar usando retornos fictícios. Casos planejados ainda não implementados ficam rastreados neste documento; não criar dezenas de testes vazios/xfail para simular cobertura.

Para cada caso implementado registrar: ID, função/contrato, fixture, preparação, estímulo, resultado esperado e efeitos proibidos. Nomes sugeridos: `test_<funcao>_<cenario>`. As linhas das tabelas abaixo são famílias de casos: sucesso, limite e erro devem virar testes separados quando isso facilitar identificar falhas.

Critério por módulo: todos os contratos aplicáveis exercitados, saídas/erros comparados a expectativas independentes e nenhuma dependência proibida. Cobertura de linhas é diagnóstico complementar, não substitui cenários. Métodos privados são cobertos pelo comportamento público, sem congelar algoritmos internos.

## 2. Estrutura da suíte e fixtures

```text
tests/
  structure/                 # imports, fronteiras, stubs
  unit/debuginfo/
  unit/target/
  unit/session/
  unit/eval/
  unit/ui/
  contract/                  # matriz Target reutilizável
  scenarios/                 # casos de uso com FakeTarget
  golden/                    # texto normalizado e JSON esperado
  integration/               # live, opt-in
  fixtures/
    sdcc/                    # fontes + lst/map/cdb + versão/flags
    malformed/               # corrupção mínima e origem documentada
    macros/                  # defines, contexto e expansões esperadas
    memory/                  # imagens de 64 KiB e registradores
    protocol/                # transcrições XML independentes
```

| Fixture | Conteúdo necessário | Oráculo |
| --- | --- | --- |
| FX-MAP | Públicos, pseudo-símbolos sem módulo, paginação | Lista revisada de símbolos/endereços |
| FX-LST | Áreas reentrantes, linha C pendente, EQU, relocação, labels | Offsets/linhas extraídos manualmente de amostra pequena |
| FX-CDB | F/S/L/T, statics homônimos, blocos, registers, função sem exit | Identidades e escopos esperados revisados |
| FX-MULTI | Residente/DLL, módulo repetido, endereços sobrepostos, bases conflitantes | Candidatos por imagem, sem escolha arbitrária |
| FX-TYPES | Todos os primitivos, structs aninhadas, arrays, tipos rejeitados | Bytes e layouts calculados independentemente |
| FX-MACRO | Objeto/função, nested args, condições desconhecidas, ciclos | Tokens expandidos e resultado aritmético distintos |
| FX-CPU | PC/SP/IX, 64 KiB, cadeia IX e código de prólogo/epílogo | Frames/endereço de variável esperados |
| FX-XML | Handshake, ok/nok, fragmentos, eventos, truncamento | Conteúdo e erros esperados sem depender do serializador testado |

Cada fixture real SDCC deve incluir fonte, versão, flags e modo de geração. Não assumir disponíveis os 344 testes citados na SPEC. Casos sintéticos mínimos complementam fixtures reais e não substituem validação do formato.

Doubles: `FakeClock` avança sem dormir; token de cancelamento muda em passo predeterminado; reader de memória conta acessos; transporte scripted injeta falha antes/depois do envio; dependência proibida lança AssertionError se chamada. Expectativas não devem ser geradas pelo mesmo parser/decoder sob teste.

## 3. Verificação estrutural dos stubs (S)

- Importar cada módulo em subprocesso isolado; falhar se abrir socket, executar processo, controlar target ou carregar artefatos de projeto. Imports normais de bibliotecas podem ler seus próprios arquivos.
- Compilar/importar com Python 3.9 e uma versão adicional suportada. Apenas parsear sintaxe numa versão recente não comprova compatibilidade com 3.9.
- Comparar inventário público e assinaturas com MODULE_DESIGN, incluindo os módulos extras e F17/F18. Construtores triviais e DTOs são verificados estruturalmente, sem testes que apenas repetem dataclasses.
- Verificar grafo de imports, inclusive imports tardios: session não importa eval/ui, target não importa debuginfo, renderizador não acessa Target.
- Instanciar serviços com doubles mínimos e comprovar que construtores não executam I/O. Operações concretas ainda não implementadas devem lançar NotImplementedError identificável, sem retorno fictício.
- Não aplicar a exigência de NotImplementedError a DTOs, enums, exceções, métodos de Protocol ou construtores que apenas armazenam dependências.
- Ao implementar uma operação, substituir sua expectativa de stub pelos testes funcionais; não manter testes exigindo NotImplementedError para sempre.

## 4. `debuginfo`: matriz por módulo e função

### `debuginfo/diagnostics.py` e `debuginfo/model.py`

| ID | Alvo | Casos e resultado esperado |
| --- | --- | --- |
| D01 | Origin, Diagnostic, ParseResult, ProjectLoadError | Erro mantém path/linha/record_kind e todas as origens conflitantes; resultado parcial conserva registros válidos; nenhuma impressão direta |
| D02 | Identidades ImageId/ModuleId/FunctionId/VariableId/TypeId | Mesmo nome em imagens/módulos/blocos diferentes não colide em índices; mesma identidade reconhecida como duplicata |
| D03 | `AddressRange.contains` | `[0,1)` contém 0, exclui 1; `[65535,65536)` contém 65535; inversão/valores fora do domínio rejeitados pelo responsável pela validação; sem wrap |
| D04 | `Resolution.unique_or_none` | unique retorna único; missing/ambiguous retornam None sem perder status/candidatos; unique com cardinalidade inválida rejeitado |
| D05 | DTOs de modelos e Storage | Estado exposto não pode ser alterado por listas/mappings de entrada; UnknownStorage não vira endereço zero; ordem low-byte-first preservada; limites desconhecidos não viram infinito |
| D06 | Grafo TypeDef/Field | Ponteiro recursivo permitido; composição por valor recursiva rejeitada pelo loader; campos com tipo incompleto permanecem indisponíveis |

### Parsers: `map_parser.py`, `lst_parser.py`, `cdb_parser.py`, `header_parser.py`

| ID | Função | Casos e resultado esperado |
| --- | --- | --- |
| D07 | `parse_map` | **Implementado e coberto por testes.** Cabeçalho Value Global, nova página e símbolos sem módulo; endereços hex corretos; linhas fora de tabela ignoradas; linha malformada gera diagnóstico localizado e não destrói tabela válida |
| D08 | `parse_lst` | **Implementado e coberto por testes sintéticos em `tests/test_parsing_lst.py`.** Endereço em head[4:12], linha C anexada à próxima instrução, .module/default stem, exports e labels por área; reentrância mantém offset; primeiro registro no offset vence; EQU deslocado e bytes de relocação não são instruções inventadas |
| D09 | `parse_cdb` | **Implementado e coberto por fixtures sintéticas e `tests/test_parsing_cdb.py`; links F/S/X preservados para reconciliação no loader; T restrito ao subconjunto documentado.** M/F/S/L/T fora de ordem; preserva escopo completo, registradores/offset negativos/sinal; L de função, variável e linha não confundidos; exit ausente mantido desconhecido; sloc preservado para filtragem ou ocultado conforme contrato, nunca exposto como local útil |
| D10 | `parse_headers` | Comentários, múltiplos headers, macros constantes e arrays, layout packed e aninhado; tipo desconhecido, ponteiro declarador, bitfield, union e ciclo geram erro por struct; dependentes inválidos e tipos independentes corretos; não segue include nem executa expressão Python |

Para D07–D10 adicionar arquivo vazio, fim truncado, linha muito longa e registro válido após erro. Não impor diagnóstico a uma linha irrelevante que o formato manda ignorar. CDB T só ganha sucesso para o subconjunto demonstrado em fixtures.

### `debuginfo/loader.py`

| ID | Função | Casos e resultado esperado |
| --- | --- | --- |
| D11 | `ProjectLoader.discover` | **Implementado; testes de descoberta/carga em `tests/test_project_loading.py`.** Ordem estável mesmo com ordem de diretório alterada; None descobre, tupla explícita substitui; lista vazia explícita não dispara descoberta; diretório ausente/arquivo inacessível tem diagnóstico |
| D12 | `ProjectLoader.load` | **Implementado e testado para MAP/LST/CDB e fallback explícito de headers/macros.** Imagem simples e FX-MULTI; todos os CDBs reconciliados, inclusive links cruzados; bases majoritárias com avisos, empate sem escolha; ids duplicados falham antes de parsing; tipos e macros têm origem; arquivo essencial ausente falha, struct opcional inválida não invalida projeto |
| D13 | `read_project_spec` | **Schema JSON v1 implementado.** JSON válido/versionado, paths relativos ao manifesto, duplicatas e versão desconhecida; opções conflitantes rejeitadas antes da conexão |

### `debuginfo/index.py`

| ID | Método | Casos e resultado esperado |
| --- | --- | --- |
| D14 | `Project.resolve` | **Implementado no incremento offline; testes em `tests/test_project_loading.py`.** Início/fim de módulo, gaps, imagem filtrada e sobreposição; propriedade vem da base, não nearest_symbol; áreas não suportadas permanecem não resolvidas; fallback limitado traz evidência |
| D15 | `Project.resolve_line` | **Implementado no incremento offline; testes em `tests/test_project_loading.py`.** Linha exata, próxima com código e inexistência posterior; map.c não casa worldmap.c; mesmo basename em duas pastas retorna ambiguidade; imagem e linha efetiva preservadas |
| D16 | `Project.lookup_symbol` | **Implementado no incremento offline; testes em `tests/test_project_loading.py`.** Nome exato antes de alias sem `_`; ausente e múltiplos candidatos; símbolos iguais em duas imagens não colapsam |
| D17 | `Project.nearest_symbol` | **Implementado no incremento offline; testes em `tests/test_project_loading.py`.** Exato/offset positivo, endereço antes do primeiro símbolo, empate entre imagens; resultado não altera propriedade do módulo |
| D18 | `Project.function_at` | **Implementado no incremento offline; testes em `tests/test_project_loading.py`.** Entry, último byte, fim exclusivo, função seguinte, saída inclusiva convertida; função final sem limite não captura toda memória; statics homônimos distintos |
| D19 | `Project.find_variable` | **Implementado no incremento offline; testes em `tests/test_project_loading.py`.** Local em contexto, global/static de fallback, homônimos e contexto ambíguo; símbolo fora de escopo não escolhido silenciosamente |
| D20 | `Project.variables_in_scope` | **Implementado no incremento offline; testes em `tests/test_project_loading.py`.** Antes da primeira linha retorna vazio; parâmetros por bloco sem linhas; limites de bloco; filtros locals/parameters/all; sloc não aparece |
| D21 | `Project.lookup_type` | **Implementado no incremento offline; testes em `tests/test_project_loading.py`.** Primitivo, struct por imagem, alias, ausente/ambíguo; layout rejeitado não é oferecido como utilizável |
| D22 | `Project.type_by_id` | **Implementado no incremento offline; testes em `tests/test_project_loading.py`.** Id exato e referências aninhadas; id inexistente produz erro de contrato, não tipo padrão |
| D23 | `Project.completion_catalog` | **Implementado no incremento offline; testes em `tests/test_project_loading.py`.** Fontes/símbolos/tipos previstos, nomes determinísticos, sem acesso ao emulador; preservar qualificações necessárias |

### `debuginfo/sources.py` e `debuginfo/macros.py`

| ID | Método/função | Casos e resultado esperado |
| --- | --- | --- |
| D24 | `SourceRepository.locate` | Absoluto, source-root, pai do listing; prioridade documentada, ausência e candidatos da mesma prioridade; não escolher caminho parecido por sufixo textual |
| D25 | `SourceRepository.read_window` | Primeira/última linha, arquivo curto, janela 11 linhas e 3+3 da parada; arquivo indisponível retorna diagnóstico/fallback; edição observável atualiza cache |
| D26 | `SourceRepository.invalidate` | Um path elimina só sua entrada; None invalida tudo; invalidar ausente é inofensivo |
| D27 | `parse_macro_definitions` | Objeto, parâmetros vazios versus None, continuação de linha, origem/contexto; condicional indeterminado, #undef/redefinição sem contexto, #/##/variádica necessária geram diagnóstico; não coleta todos os ramos como ativos |
| D28 | `MacroCatalog.lookup` | Contexto único resolve; homônimos em unidades/imagens não escolhem primeiro; inexistente/ambíguo explícitos; conflito hex/bin diagnosticado |
| D29 | `MacroCatalog.names` | Nomes visíveis no contexto, resultado determinístico, sem I/O vivo; nome ambíguo não é apresentado como definição resolvida |

## 5. `target`: contrato reutilizável

### `target/api.py`

T03–T20 estão implementados para FakeTarget e OpenMSXTarget, com transcrições independentes do transporte em `tests/test_phase6_openmsx_target.py`; a aprovação live permanece na etapa opt-in. Protocol Target não possui implementação própria e FakeTarget não conhece Tcl.

| ID | Método | Casos e resultado esperado |
| --- | --- | --- |
| T01 | `RegisterSet.get` | Pares, registradores especiais, shadow e todas as metades; maiúsculas/minúsculas; nome inexistente rejeitado; bits corretos em 0xABCD |
| T02 | `RegisterSet.width` | 8/16 bits conforme registrador, metades e nome inválido; mesma normalização de get |
| T03 | `Target.execution_status` | running/stopped; resposta ilegível não vira stopped |
| T04 | `Target.read_registers` | Conjunto completo, widths corretas; campo ausente/fora do formato gera erro, não zero |
| T05 | `Target.read_memory` | **Fallback agregado e caminho `read_block` binário-seguro implementados.** 0 bytes sem leitura remota, 1 byte em 65535, 64 KiB desde zero, 00/FF; negativos e overflow rejeitados; truncamento remoto gera erro |
| T06 | `Target.disassemble` | Endereço/count válidos, operandos longos, bytes e tamanhos; resposta inválida não cria instrução; count inválido explicitamente rejeitado |
| T07 | `Target.read_pages` | Quatro páginas, slots primários/expandidos, MapperIO e fallback; segmento desconhecido permanece desconhecido |
| T08 | `Target.continue_execution` | Uma emissão, aceitação não implica parada; timeout pós-envio com outcome_unknown, sem retry |
| T09 | `Target.step_into` | Uma emissão e sequência running→stopped separada da resposta do comando |
| T10 | `Target.step_over` | Chamada distinta de step_into; não assumir uma instrução total executada |
| T11 | `Target.step_out` | Aceitação antes da parada possível; caller deve consultar status |
| T12 | `Target.run_to` | Endereços 0/65535; fora do domínio rejeitado antes de I/O; timeout sem reenvio |
| T13 | `Target.interrupt` | Solicitação aceita ainda exige confirmação; falha de comunicação não fabrica parada |
| T14 | `Target.create_breakpoint` | Retorna id remoto real; nok não cria sucesso; timeout antes/depois do envio diferenciado |
| T15 | `Target.remove_breakpoint` | Id correto, remoto ausente/erro preservado; texto com caracteres especiais corretamente serializado |
| T16 | `Target.list_breakpoints` | Lista vazia, próprios/externos no mesmo endereço e dados malformados; sem remoção implícita |
| T17 | `Target.reset` | Somente transporte falso: comando correto, erro normalizado, nenhuma chamada extra |
| T18 | `Target.save_state` | Somente transporte falso: nome com espaços/caracteres especiais é um argumento Tcl, não código |
| T19 | `Target.load_state` | Somente transporte falso: sucesso, estado ausente e timeout; sem retry |
| T20 | `Target.close` | Idempotente; fecha recursos sem continue/reset/load/encerrar emulador |

DTOs Instruction/PageState/RemoteBreakpoint/TargetCapabilities e exceções: validar conservação dos campos e erro `outcome_unknown` nos cenários acima, sem testes redundantes de cada getter trivial.

### `target/transport.py`, `target/openmsx.py`, `target/fake.py`

| ID | Método/função | Casos e resultado esperado |
| --- | --- | --- |
| T21 | `OpenMSXTransport.request` | **Modos per-command e persistent implementados e cobertos em `tests/test_phase6_transport.py`.** Handshake e replies XML incrementais, fragmentação byte a byte, ok/nok, entidades, eventos intercalados, timeout antes/depois do envio, EOF, XML inválido; persistente descarta conexão defeituosa sem retry de mutação |
| T22 | `OpenMSXTransport.drain_events` | **Implementado com fila limitada a 256 eventos e overflow observável.** Preserva ordem, eventos podem compartilhar blocos do handshake/reply e a segunda drenagem retorna vazio |
| T23 | `OpenMSXTransport.close` | **Implementado e idempotente para per-command.** Impede novas requisições e não executa nenhuma operação no alvo |
| T24 | `discover_socket` | **Implementado e coberto em `tests/test_target_contracts.py`.** Path explícito aceita somente socket Unix; descoberta escolhe o mais recente por mtime, desempata pelo caminho e ignora arquivos comuns; ausência gera `TargetUnavailable` com mensagem attach-only |
| T25 | `OpenMSXTarget.__init__` | **Implementado; T03–T20 cobrem o adaptador com transporte scripted.** Apenas armazena transporte/capacidades; nenhum comando ou detecção mutável |
| T26 | `FakeTarget.__init__` | Memória/regs/script isolados de objetos de entrada; tamanho de memória inválido rejeitado; aceita breakpoints preexistentes na preparação prevista |
| T27 | `FakeTarget.inject_failure` | Falha antes não aplica; after_apply aplica e falha; chamada seguinte não repete mutação implicitamente |
| T28 | `FakeTarget.calls` | Ordem e argumentos tipados, snapshot não mutável; chamada inesperada falha em vez de ser aceita |

T21 deve testar XML escaping e quoting Tcl em camadas distintas. Strings contendo `<>&`, chaves, aspas, ponto e vírgula, `$` e colchetes não podem alterar o número/estrutura dos comandos. T01/T02 do BACKLOG (persistência/blocos) ganham testes adicionais por capacidade: mesmo resultado que fallback e redução mensurável de chamadas, sem limiar frágil de tempo de parede.

## 6. `session`: estado e casos de uso

### `session/state.py` e `session/results.py`

| ID | Alvo | Casos e resultado esperado |
| --- | --- | --- |
| S01 | StopSnapshot/SelectionState/StopCache/SessionConfig/SignatureSpec | Nova parada incrementa geração e frame zero; seleção não altera snapshot; ranges e limites inválidos recusados; memória desconhecida não vira bytes zero |
| S02 | `InspectionContext.stop_id` | Corresponde à geração capturada, não muda com outra seleção; acesso após invalidação rejeitado |
| S03 | `InspectionContext.frame` | Frame capturado permanece fixo durante avaliação; contexto obsoleto rejeitado |
| S04 | `InspectionContext.registers` | Registradores vivos da parada, inclusive quando frame selecionado é caller; não inventa registradores salvos |
| S05 | `InspectionContext.symbol_context` | Caller usa PC de escopo correto; imagem ambígua não é resolvida arbitrariamente |
| S06 | `InspectionContext.read_memory` | Cache reutiliza leitura na parada; faixas sobrepostas retornam bytes corretos; geração nova relê; falha não envenena cache |
| S07 | `InspectionContext.locate_variable` | Encaminha frame/regs corretos; retorno indisponível conserva motivo; sem decode ou renderização |
| S08 | `InspectionContext.validate` | Alvo parado válido; retomada observada ou geração antiga falha; cenário de concorrência invisível não é prometido como detectável |
| S09 | StopResult/ResolvedTarget/LocationResult/DisassemblyResult/CloseReport | Preservam ambiguidades, avisos, ids pendentes e indisponibilidade; resultados não contêm markup ou estruturas internas de transporte |

### `session/core.py`

| ID | Método | Casos e resultado esperado |
| --- | --- | --- |
| S10 | `Session.__init__` | Dependências/configuração armazenadas, sem attach ou leitura; estado inicial disconnected |
| S11 | `Session.attach` | Running não é pausado; stopped captura snapshot; falha de transporte não afirma stopped |
| S12 | `Session.reconcile` | Recupera estado observável e próprios ids; não recria breakpoint nem reenvia execução após timeout |
| S13 | `Session.resolve_target` | Endereço válido sem fonte aceito; símbolo/linha único, ausente e ambíguo; avanço de linha preservado; nenhuma mutação remota |
| S14 | `Session.execute` | Um caso por ExecutionKind; invalida antes de enviar; nova parada seleciona frame zero; falha pós-envio deixa unknown |
| S15 | `Session.where` | Confere parada e reapresenta sem zerar frame selecionado nem criar nova geração artificial; alvo running rejeitado |
| S16 | `Session.inspection` | Obtém contexto somente com parada válida; assinatura pending bloqueia interpretação C, permite bruto; inválido não lê variáveis |
| S17 | `Session.backtrace` | Encaminha snapshot correto, reusa cache da parada e invalida na seguinte; sem CDB informa impossibilidade |
| S18 | `Session.select_frame` | 0 e caller existente; negativo/fora da lista falham sem mudar seleção; não escreve PC |
| S19 | `Session.add_breakpoint` | Endereço resolvido preservado na criação; resultado incerto conservado; sem resolver localização novamente na apresentação |
| S20 | `Session.delete_breakpoint` | Encaminha número local correto; erro remoto mantém acompanhamento |
| S21 | `Session.suspend_breakpoint` | Segunda chamada não remove novamente; mantém número/endereço |
| S22 | `Session.resume_breakpoint` | Segunda chamada ativa não duplica; erro conserva estado explícito |
| S23 | `Session.breakpoints` | Somente registros da sessão, ordem estável, inclui suspended/unknown |
| S24 | `Session.disassemble` | PC e anotações corretas; candidatos ambíguos preservados; contagem/endereço inválidos rejeitados |
| S25 | `Session.pages` | Dados do target sem interpretação incorreta de imagem; falha propagada |
| S26 | `Session.page3` | Política injetada, limites ausentes/invalidos e resultado desconhecido; sem constante do projeto embutida |
| S27 | `Session.set_mode` | C/asm altera modo, não executa CPU nem invalida memória; valor inválido rejeitado |
| S28 | `Session.save` | Nome interno de sessão, única operação; erro relatado; sem criação arbitrária de argumentos |
| S29 | `Session.reset` | Permit correto consumido antes da emissão; inválido/reutilizado não toca target; invalida snapshot e rearma assinatura; erro não permite reuso |
| S30 | `Session.load` | Mesmas garantias de permit/invalidação; estado ausente traduzido corretamente; sem restore automático |
| S31 | `Session.close` | Limpa todos os próprios ids apesar de falha individual; preserva externos, relata id desconhecido, fecha transporte; idempotente, não mascara exceção original |

### `session/execution.py`

| ID | Método/contrato | Casos e resultado esperado |
| --- | --- | --- |
| S32 | `ExecutionController.run` | Continue, step, next, stepi, finish e until esperam status stopped; modo C para em mudança de imagem/módulo/arquivo/linha, breakpoint ou unresolved; modo asm dá um passo; stepi apresenta asm |
| S33 | `ExecutionController.run` — limites | 20.000 passos solicitados, timeout global não reinicia por iteração; cancelamento antes/durante espera; interrupção confirmada retorna parada, sem confirmação vira unknown; não lê snapshot prematuramente |
| S34 | `Clock.monotonic` | Double monotônico torna deadline reproduzível, independente do relógio civil |
| S35 | `Clock.sleep` | FakeClock avança virtualmente, registra intervalo; teste não dorme 50 ms reais por poll |
| S36 | `CancellationToken.is_cancelled` | Falso, transição em poll definido e verdadeiro inicial; cancelamento observado sem thread/race artificial |

### `session/breakpoints.py`

| ID | Método | Casos e resultado esperado |
| --- | --- | --- |
| S37 | `BreakpointManager.create` | Número monotônico reservado mesmo em falha; id remoto correto; timeout pós-criação mantém unknown sem inventar id |
| S38 | `BreakpointManager.delete` | Remoto primeiro; sucesso remove local; falha conserva; número inexistente não toca target |
| S39 | `BreakpointManager.suspend` | Remove ativo, conserva número; suspenso idempotente; timeout não confirma suspensão |
| S40 | `BreakpointManager.resume` | Recria suspenso com novo id e mesmo número/endereço; ativo idempotente; timeout sem retry |
| S41 | `BreakpointManager.records` | Snapshot não mutável, todos os estados, sem externos |
| S42 | `BreakpointManager.matching` | Todos os números ativos no endereço, exclui suspended/unknown; endereço diferente retorna vazio |
| S43 | `BreakpointManager.reconcile` | Confirma id próprio presente/ausente; não toma posse por coincidência de endereço; criação sem id permanece incerta quando não há prova |
| S44 | `BreakpointManager.cleanup` | Remove ids próprios conhecidos, continua após falha; relata pendências e não duplica remoções já confirmadas |

### `session/frames.py`, `session/safety.py`, `session/memory_map.py`

| ID | Método | Casos e resultado esperado |
| --- | --- | --- |
| S45 | `FrameService.walk` | 0/1/múltiplos callers; return_addr exibido versus return_addr−1 de escopo; ciclo IX, 64 frames, endereço inválido, função desconhecida e caller sem frame encerram com motivo |
| S46 | `FrameService.frame_state` | Prólogo IX exato, antes/depois de prólogo, epílogo e ramos com pop não demonstrado; desconhecido em vez de palpite; função homônima em outra imagem não compartilha cache |
| S47 | `FrameService.locate` | E absoluto, B IX + offset positivo/negativo, SP entry demonstrado, bytes de registradores low-first; caller sem IX e caller com variável em registrador indisponíveis; stack fora do domínio não sofre wrap silencioso |
| S48 | `SafetyGate.authorize_typed` | Literal fresh-input reset yes/load yes; bare, capitalização distinta, replay, batch e ação divergente recusados sem I/O; teste com entrada sintética não representa autenticação humana |
| S49 | `SafetyGate.consume` | Uma utilização, sessão/ação corretas; troca entre ações/sessões e reuso após erro rejeitados |
| S50 | `SignatureGuard.check` | Sem config não lê; pending compara bytes; match fica verified; erro não marca verified; leituras posteriores obedecem cache do guard |
| S51 | `SignatureGuard.rearm` | Verified volta a pending; nova leitura necessária; sem config continua not-configured |
| S52 | `MemoryMapService.page3` | Dados/heap/free/stack/reserva, topo TPA, limites 0xC000/0x10000; heap igual/acima SP avisa; símbolo ausente e regiões invertidas não geram número livre inventado |

## 7. `eval`: expressões, macros e valores

### `eval/tokens.py`, `eval/ast.py`, `eval/parser.py`, `eval/macros.py`

| ID | Função/método | Casos e resultado esperado |
| --- | --- | --- |
| E01 | `tokenize` | Decimal/0x/#hex, identifiers, operadores, colchetes, parênteses, vírgulas e espaços; offsets corretos; token inválido/truncado aponta intervalo; não executa texto |
| E02 | AST | Group não representa indirection; Indirect explícito; BuiltinCall só hex/bin após expansão; árvore preserva precedência e origem |
| E03 | `ExpressionParser.parse_expression` | +/− unário, */ antes de +/−, associatividade, agrupamento; entrada vazia, sobra de tokens e delimitadores desequilibrados falham; não aceita chamada C arbitrária |
| E04 | `ExpressionParser.parse_print` | ExpandedTokens com cálculo, memória explícita, tipo externo e indexação; parênteses sem tipo calculam; não remove delimitadores de `(hl+3)*(hl)`; rejeita builtin externo com tipo de memória conforme COMMANDS |
| E05 | `MacroExpander.expand` | Objeto encadeado, função, zero argumentos, parâmetros repetidos, chamadas aninhadas e vírgulas em parênteses; aridade incorreta, ciclo direto/indireto, limite de tokens/profundidade e definição ambígua falham com cadeia de origem |
| E06 | `MacroExpander.expand` — semântica textual | `#define M 1+2`: `M*3` expande sem parênteses adicionais e resulta em 7; macro que pede operador não suportado não executa nada; #/##/variádica não suportados diagnosticados; hex/bin reservados |

Não impor semântica de pré-processador C completo no oráculo. Testar a expansão de tokens separadamente da avaliação; uma coincidência numérica não prova expansão correta.

### `eval/values.py` e `eval/evaluator.py`

| ID | Função/método | Casos e resultado esperado |
| --- | --- | --- |
| E07 | `ValueDecoder.decode` | Todos os tipos/aliases de COMMANDS: zeros, máximos, sinal mínimo, little-endian, bool, char imprimível/escape, ptr; float com bytes IEEE explícitos sem presumir ABI do compilador; bytes insuficientes falham |
| E08 | `ValueDecoder.decode` — compostos | String vazia/NUL/Latin-1/256 sem NUL; structs aninhadas e arrays 0/1/16/17; truncamento informado; tipo incompleto/ciclo por valor rejeitado; nenhuma leitura remota dentro do decoder |
| E09 | `default_print_type` | Escalares CDB por tamanho/sinal; ponteiro/array/struct sem default; largura desconhecida explícita; não aplica automaticamente política distinta de info locals |
| E10 | `Evaluator.__init__` | Armazena dependências/limites, sem consulta de Target ou parsing de arquivos |
| E11 | `Evaluator.evaluate_address` | Aritmética inteira, registradores/MAP, negativo e 65536 convertidos no limite final de 16 bits; sem leitura automática do endereço avaliado; erro de nome/zero division explícito |
| E12 | `Evaluator.requirements` | Após expansão: constante e MAP conhecido usado como endereço em cálculo não exigem target; registrador, CDB vivo e memória exigem contexto; desconhecido/ambíguo falha ou requisita contexto necessário para resolver, nunca é considerado constante por padrão |
| E13 | `Evaluator.evaluate_print` | Matriz E17–E29 abaixo; contexto opcional apenas para cálculo independente; contexto obsoleto falha; leitura de struct uma vez; registrador isolado mantém aviso de tipo ignorado |
| E14 | `Evaluator.evaluate_variables` | Locals/args escalares, ponteiro simples como u16 e composto bruto; variável indisponível não derruba tabela; ressalva de register live ranges; contexto único sem leituras repetidas desnecessárias |
| E15 | ValueResult/DecodedValue/VariableRow | Espécie/base/localização coerentes; cálculo não finge bytes de memória; indisponível não vira zero; bytes preservados para diagnóstico |
| E16 | Cálculo inteiro | Divisão de inteiros grandes não passa por float; resultados >64 bits permanecem exatos; não aplicar wrap de endereço a valor escalar |

### Casos obrigatórios F17/F18

Todos verificam valor, espécie e base, além da ausência/presença correta de I/O.

| ID | Entrada/preparação | Resultado esperado |
| --- | --- | --- |
| E17 | `print 2 + 3 * 4`; target-proibido | 14, calculation, base 10, zero chamadas Target |
| E18 | `print (2 + 3) * 4` | 20; parênteses agrupam |
| E19 | `print 65535 + 1` | 65536 sem truncamento |
| E20 | `print -7 / 3` e `print 7 / -3` | −2 em ambos; `/0` produz erro |
| E21 | `print hex(255)`; `print bin(10)` | Valores 255/10, base 16/2; texto 0xff/0b1010 |
| E22 | `print hex(-10)`; `print hex(bin(10)+1)` | −10 base 16, texto −0xa; 11 base 16, texto 0xb |
| E23 | `print hex(10)+1`; `hex()`; `bin(1,2)` | 11 base 10; chamadas de aridade inválida falham |
| E24 | HL=0x8000: `print (hl)` versus `print [hl]` | Primeiro mostra 32768 sem ler memória; segundo lê u8 em 0x8000 |
| E25 | `print 0xC000 u16`; `print/u16 hl + 3` | Mantêm leitura de memória tipada nos endereços calculados |
| E26 | `_x` MAP=0x8000, memória=7: `print _x`; `print _x+1` | Primeiro lê 7 como u8; segundo calcula endereço 32769, sem dereferência |
| E27 | `#define MY_OFFSET 0x20`; `print [0x8000+MY_OFFSET] u16`; bytes 34 12 | Lê em 0x8020 e retorna 4660 |
| E28 | `#define NLV(a,b) ((a)+(b))`; MAPs 0x100 e 0x200; `print NLV( _g_teste,_g_outro_teste)` | 768 como cálculo; não lê os endereços; macro apenas de fixture |
| E29 | Macro ausente/ambígua/cíclica; `print NLV(a)` | Erro específico com origem/aridade; nenhum fallback para chamada de função do programa |

Adicionar caso de variável CDB tipada na aritmética: somar valor, não endereço. Macro constante deve funcionar em sessão running/unknown sem inspeção, desde que catálogo/contexto offline resolvam a definição. Não declarar que o CLI shell deixa de exigir attach: a independência aqui é da avaliação, não um novo subcomando offline.

## 8. `ui`: funções e handlers

### `ui/results.py` e `ui/registry.py`

Os payloads de apresentação são uma união fechada implementada em `ui/results.py`: parada, breakpoint(s), registradores, páginas, símbolo, fonte, disassembly, frames, valores, mensagens, ajuda e ações. Os renderizadores rejeitam tipos desconhecidos em vez de serializar objetos internos implicitamente.

| ID | Alvo | Casos e resultado esperado |
| --- | --- | --- |
| U01 | CommandResult/CommandError/UiAction | ok versus erro coerentes; falha sem payload de sucesso; detalhes estruturados; ação clear/quit não executada pelo renderizador |
| U02 | `CommandRegistry.register` | Nome novo e aliases aceitos; qualquer duplicata rejeitada sem registro parcial |
| U03 | `CommandRegistry.lookup` | Nome/alias apontam ao mesmo spec; desconhecido produz erro útil |
| U04 | `CommandRegistry.specifications` | Ordem determinística e todos os comandos sem duplicar aliases como comandos principais |
| U05 | `CommandRegistry.complete` | Cursor no meio/final, primeiro token, info, print, arquivo:linha e macros/builtins; sem I/O alvo; não aceita automaticamente sugestão |

### `ui/commands.py`: dispatcher e cada handler

O encaminhamento dos handlers U09–U32 para os casos de uso de Session, avaliação e ações de UI está implementado e coberto inicialmente por `tests/test_phase5_handlers.py`. A aprovação funcional individual continua condicionada aos serviços ainda explicitamente pendentes — especialmente `SourceRepository`, `MemoryMapService` e `SafetyGate` — e aos payloads/renderizadores completos da etapa seguinte.

| ID | Função | Casos e resultado esperado |
| --- | --- | --- |
| U06 | `build_registry` | **Registro completo implementado e coberto por `tests/test_phase5_registry.py`.** 24 comandos documentados e todos os aliases, inclusive bt/advance/?; help/completion derivam dos mesmos specs; reset/load não repetíveis |
| U07 | `parse_target` | **Implementado e coberto por formas válidas e inválidas.** Decimal, 0x, símbolo e path:linha; imagem:: antes de separador de linha; rejeitar alvo incompleto/linha inválida e aritmética não prometida para break |
| U08 | `CommandDispatcher.dispatch` | Alias canonicalizado, argumento completo preservado, erro de parser/handler vira CommandResult; política de segurança não removida; não interpreta shell pipes/; como comandos extras |
| U09 | `handle_break` | Único cria; ambíguo/ausente não cria; endereço bruto sem fonte funciona |
| U10 | `handle_delete` | Número obrigatório válido; não aceita id remoto; erro não apaga acompanhamento |
| U11 | `handle_suspend` | Número e aliases, idempotência observável |
| U12 | `handle_resume` | Número e aliases, sem criação duplicada |
| U13 | `handle_continue` | ExecutionKind continue, espera/relatório, rejeita argumentos não previstos |
| U14 | `handle_step` | Modo atual C/asm e pedido step; não aceita contagem inventada |
| U15 | `handle_next` | Pedido next/step-over distinto de step |
| U16 | `handle_stepi` | Pedido stepi e estilo asm mesmo no modo C |
| U17 | `handle_finish` | Pedido finish aguarda stop; nunca renderiza estado running como parada |
| U18 | `handle_until` | Alvo obrigatório e nota de linha efetiva; sem emissão se ambíguo |
| U19 | `handle_where` | Preserva frame selecionado e usa snapshot validado |
| U20 | `handle_backtrace` | Lista/razão de término; indisponibilidade CDB explícita |
| U21 | `handle_frame` | Sem argumento mostra seleção; índice escolhe; inválido preserva seleção |
| U22 | `handle_list` | Sem alvo, número, arquivo:linha, next/previous; cursor e janela 11; início/fim/fonte ausente |
| U23 | `handle_disassemble` | PC padrão, endereço/count, símbolo proposto, next/previous; cursor correto, navegação anterior descrita como aproximada |
| U24 | `handle_print` | Tipo/aliases, tokens→macros→AST; requirements antes de inspection; E17–E29; macro com espaços/vírgulas não é quebrada em argumentos de comando |
| U25 | `handle_info` | Cada subcomando/alias na matriz abaixo; aridade inválida e nome desconhecido |
| U26 | `handle_mode` | Mostrar/setar c/source/asm/assembly; modo inválido sem alteração |
| U27 | `handle_save` | Sem argumento, nome interno, erro propagado; não aceita nome externo |
| U28 | `handle_reset` | Bare explica; literal novo recebe permit; batch/repeat negados antes de Target |
| U29 | `handle_load` | Bare explica; permit consumido; save ausente orienta usuário; sem restore automático |
| U30 | `handle_clear` | UiAction de limpar tela/scrollback, sem Target; política batch depende de decisão documentada |
| U31 | `handle_help` | Todos os comandos e aliases, sem sintaxe futura apresentada como disponível |
| U32 | `handle_quit` | UiAction termina loop; composição realiza cleanup, sem encerrar openMSX |

`handle_info` deve ter sete casos independentes: registers/reg/regs (16 registradores principais); breakpoints/break/b (estados); pages/page/slots/segments (4 páginas); symbol/sym (expressão inteira e símbolo próximo sem ler valor); page3/free (conhecido/desconhecido/corrupção); locals/local; args/arguments (frame/escopo/tabela vazia). Não inventar métodos públicos para esses subdispatches antes de existirem no desenho.

### `ui/repl.py`, `ui/batch.py`, `ui/render_text.py`, `ui/render_json.py`

| ID | Método | Casos e resultado esperado |
| --- | --- | --- |
| U33 | `Repl.run` | **Política de repetição e ações implementada.** Histórico em memória; vazio repete permitido, nunca reset/load; EOF/quit retornam; Ctrl-C no prompt/despacho não encerra; erro de comando mantém loop |
| U34 | `BatchRunner.run` | **Deadline, origem batch, restauração de contexto e erros estruturados implementados.** Ordem, um envelope por executado, primeiro erro interrompe, stdout puro, deadline global `--timeout` positivo (30 s por padrão); reset/load/clear recusados antes de efeitos; não escreve sucesso para comando não executado |
| U35 | `TextRenderer.render` | Golden para cada espécie de payload; markup malicioso em nome/fonte escapado; cálculo hex/bin, sinais e memória distintos; nenhuma dependência viva |
| U36 | `JsonRenderer.encode` | Objeto sem newline; envelope v1 sempre contém schema_version/command_index/command/ok/data/warnings/error; número e display_base preservados, inteiros grandes sem conversão float; bytes explicitamente codificados, NaN/Infinity normalizados; schema não expõe campos internos acidentalmente |

Fixar largura e opções de cor nos goldens; normalizar somente paths temporários e ids variáveis previamente identificados. Não normalizar valores, endereços ou mensagens que constituem o comportamento sob teste. Repl pode usar input/output injetados, sem desktop ou teclado real.

## 9. `__main__.py` e pacote

| ID | Função | Casos e resultado esperado |
| --- | --- | --- |
| C01 | `main` | **Dispatch de resolve/shell/exec/version implementado.** Códigos 0/1/2; erro de inicialização/cleanup em stderr; import não executa main |
| C02 | `build_argument_parser` | **Opções de resolve/shell/exec implementadas, incluindo `--timeout` e `--json`.** Opções e repetições documentadas, obrigatórios e uso inválido |
| C03 | `run_resolve` | **Implementado; goldens sintéticos e testes de subprocesso em `tests/test_resolve_cli.py`.** FX-MULTI e arquivo:linha, stdout de sucesso, unresolved/ambiguidade; nenhuma instanciação de Target/Session/socket |
| C04 | `run_shell` | **Composição, tratamento de falhas e attach live implementados e validados no openMSX 21.0.** Finally fecha em quit/EOF/exceção; falha de cleanup não mascara erro original; não inicia emulador |
| C05 | `run_exec` | **Composição, mesma Session, timeout, lifecycle e JSON live validados com os artefatos reais do msxciv.** Finally e código de saída da limpeza; reset/load impedidos |
| C06 | Pacote e `__init__.py` | Instalação/import/entrada CLI quando packaging existir; `--version` sem artefatos/socket; exports coerentes, sem side effects |

## 10. Cenários integrados e rastreabilidade

| ID | Cenário | Requisitos/defeitos |
| --- | --- | --- |
| I01 | LST+MAP de duas imagens → resolve → break → parada | F02/F03/F12, B4/B5/B6/B11 |
| I02 | continue/step/next/finish/until com parada tardia | B7, consistência e cancelamento |
| I03 | **Coberto com FakeTarget para breakpoint próprio e cleanup; casos externos/erro remoto permanecem nos testes de BreakpointManager.** Breakpoints próprios e externos, erro na exclusão, EOF | B3 e propriedade/cleanup |
| I04 | Snapshot → caller frame → locals → retomar → contexto antigo | Frames, cache e indisponibilidade correta |
| I05 | Macros carregadas → cálculo constante → texto/JSON | F04/F17/F18, B1/B2; zero I/O vivo |
| I06 | Macro MY_OFFSET → leitura tipada → mudança de parada | F18 e invalidação de cache |
| I07 | Texto com `<>&` em transporte/nomes e rich markup | B10 e escaping de UI |
| I08 | disassemble símbolo, aliases e completion | B8/B9 |
| I09 | **Coberto por `tests/test_phase5_integration.py`, batch e CommandApplication.** exec: sucesso, erro intermediário e falha de limpeza | F01, um envelope por comando executado |
| I10 | **Coberto para recusa em lote e repetição; emissão autorizada aguarda SafetyGate concreto.** reset/load via lote/repeat/permit inválido | Segurança em UI e sessão; somente FakeTarget |
| I11 | Sem CDB/sem fonte/struct rejeitada/assinatura pending | Degradação explícita sem valores presumidos |

L live: a suíte opt-in está implementada em `tests/integration/test_openmsx_live.py`, documentada no README adjacente e foi executada no openMSX 21.0 em 2026-09-29. `MSXDBG_LIVE_SOCKET` habilita somente attach/read regs/memory/disasm/pages/listagem de breakpoints; `MSXDBG_LIVE_OUT` acrescenta exec JSON read-only. Criação/remoção de breakpoint, um único `step_in` e otimizações exigem opt-ins literais separados. Nunca iniciar openMSX, inserir mídia, alterar velocidade ou automatizar reset/load. Ausência de ambiente produz skip, nunca aprovação. Resultados e limites estão em `PHASE6_VALIDATION.md`.

## 11. Funcionalidades adiadas: testes ao promover o requisito

Não criar stubs funcionais ou testes de APIs inexistentes apenas para esta matriz.

| Requisito | Casos a acrescentar quando contrato estiver definido |
| --- | --- |
| F05 | T: reais do msxciv/SDCC 4.6.0 com aliases/arrays/ponteiros e conflito de layout header/CDB |
| F06 | *p, &x, a[i], s.f, p->f; frame atual/caller/global/static, tipo correto, erro, endereço versus valor e macro com esses operadores |
| F07 | Assinatura ausente/pending/verificada; limite global, cancelamento e nenhuma continuação após match |
| F08/F09 | Condições false/true, mapper certo/errado, preserve em suspend/resume e disparo filtrado no target |
| F10 | Read/write/access, faixa/bordas, tamanho inferido/explícito, limpeza de watchpoints próprios |
| F11 | **Coberto na fase 10:** áreas HOME/GSINIT/GSFINAL com offsets repetidos e relocação independente |
| F13 | **Coberto na fase 10:** mesmo PC em imagens diferentes por segmento; falta de associação mantém ambiguidade |
| F14/F15 | **Coberto na fase 10:** alvo parado, ranges/widths, verificação após escrita, timeout sem retry e novo snapshot |
| F16 | **Coberto na fase 10:** static com base comprovada versus offset sem relocação; nenhum endereço adivinhado |

F01–F06/F12/F17/F18 estão cobertos pelas matrizes principais e pelas validações das fases 7/8. X01/X02 continuam excluídos; testar ausência de efeitos proibidos, não implementar integração para iniciar/gerenciar o emulador.

## 12. Pendências de contrato reveladas pelo plano

Resolver antes de congelar expectativas correspondentes:

- Esquema externo de manifesto; timeout e política de clear no batch foram definidos na fase 5.
- Limites numéricos de expansão e comportamento de overflow da fila de eventos.
- Seleção determinística em empate de mtime dos sockets e confirmação de capabilities live.
- Configuração externa de contexto de macros e política quando o frame necessário para resolver um nome ainda não foi capturado. Nunca classificar nome desconhecido como constante por conveniência.
- Campos exatos do schema JSON por payload, inclusive display_base e bytes; códigos de erro estáveis.
- Evidência de ABI float e estado de frame em fluxos complexos; resultado desconhecido é aceitável até prova, resultado inventado não.

Essas pendências bloqueiam apenas os testes dependentes. Nos demais, testar os contratos já definidos. Não usar o plano de testes para escolher silenciosamente novos comportamentos do produto.

## 13. Ordem de execução e conclusão

1. Stubs: executar S estrutural, imports/compilação e inventário; nenhuma promessa de comportamento funcional.
2. Offline: D01–D29 e C03 com fixtures; parser/index não requer emulador.
3. Alvo/sessão: T01–T28 e S01–S52; relógio falso e nenhuma espera longa real.
4. Avaliação: E01–E29, incluindo F17/F18 e contraste entre cálculo e memória.
5. UI/CLI: U01–U36, C01–C06 e I01–I11; goldens só após dados semânticos passarem.
6. Live: execução opt-in separada, com relatório de ambiente e capacidades verificadas.

Uma entrega funcional está concluída quando seus casos aplicáveis passam, pendências são explicitadas, nenhum efeito proibido ocorre e as regressões relacionadas passam. Registrar por caso o status planejado/implementado/aprovado/falhou/bloqueado e evidência do comando executado. Ausência de ambiente live deve aparecer como não executado, nunca como aprovação. Alterações de assinaturas públicas exigem atualizar esta matriz e o desenho juntos.
