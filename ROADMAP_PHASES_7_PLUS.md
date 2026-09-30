# msxdbg — Roadmap proposto após a fase 6

Este documento propõe a evolução do msxdbg depois da conclusão da fase 6. Ele
não altera retroativamente os critérios das fases 1–6 e não transforma itens do
backlog em funcionalidades já disponíveis. A especificação, a arquitetura e o
backlog continuam sendo as fontes dos contratos detalhados.

## Princípios de execução

- Preservar o modo attach-only: nunca iniciar openMSX, trocar mídia ou alterar
  velocidade.
- Não adicionar Tcl arbitrário como interface pública.
- Toda mutação deve ser explícita, validada e não repetida após resultado
  incerto.
- Resultados desconhecidos ou ambíguos permanecem explícitos; não selecionar o
  primeiro candidato silenciosamente.
- Cada fase deve manter os testes offline determinísticos e acrescentar live
  opt-in somente quando necessário.
- Uma fase só termina quando código, testes, documentação e critérios de
  degradação estiverem alinhados.

## Visão geral

| Fase | Tema | Resultado principal |
| --- | --- | --- |
| 7 | Fechamento do núcleo | Comandos atuais deixam de depender dos stubs restantes |
| 8 | Tipos e expressões C | Ponteiros, arrays, campos e layouts comprovados |
| 9 | Controle avançado de execução | Assinatura, condições, mapper e watchpoints |
| 10 | Áreas, imagens e memória | Novas áreas de código, seleção contextual e escritas seguras |
| 11 | Produto e distribuição | Empacotamento, compatibilidade, desempenho e preparação de release |

## Fase 7 — Fechamento do núcleo funcional

**Estado:** concluída e validada pela suíte offline; cenários live permanecem
opt-in conforme as restrições gerais do projeto.

### Objetivo

Completar os serviços ainda explicitamente parciais para que todos os comandos
já documentados tenham implementação real, degradação previsível e cobertura de
integração.

### Entregas

1. `SourceRepository`
   - localização por caminho absoluto, source roots e origem do listing;
   - ambiguidade por prioridade;
   - leitura de janelas e limites de arquivo;
   - cache observável e invalidação por arquivo ou total.
2. `SafetyGate`
   - permits de uso único para `reset yes` e `load yes`;
   - origem interativa obrigatória;
   - recusa em batch, repetição e reutilização.
3. `SignatureGuard`
   - estados não configurada, pendente e verificada;
   - rearme em reset/load;
   - bloqueio apenas da interpretação C que depende da imagem carregada.
4. `MemoryMapService.page3`
   - política de layout injetável;
   - limites conhecidos, desconhecidos e inválidos;
   - ausência de constantes específicas do msxciv no núcleo.
5. Headers e macros de projeto
   - parser de structs documentado como fallback do CDB;
   - definições com origem e contexto;
   - rejeição de condicionais e recursos não demonstrados.
6. Manifesto `--project`
   - JSON versionado;
   - paths relativos ao manifesto;
   - associação explícita de MAP/CDB por imagem;
   - regras claras de conflito com `--out`, `--map` e `--cdb`.

### Critérios de conclusão

- Nenhum método dessas áreas permanece como `NotImplementedError`.
- `list`, `info page3`, assinatura e confirmações funcionam em cenários offline
  e live opt-in aplicáveis.
- Reset/load continuam ausentes de toda automação.
- Projeto simples por `--out` permanece compatível.
- Manifestos inválidos falham antes de conectar ao emulador.

### Fora do escopo

Ponteiros e campos C, watchpoints, condições de breakpoint e escrita de estado.

## Fase 8 — Tipos compostos e expressões C

**Estado:** concluída e validada offline com fixtures extraídas do msxciv/SDCC
4.6.0, fixture C dedicada e cobertura de frame atual, caller, globals e statics.
Bitfields, unions e chamadas de função continuam fora do escopo.

### Objetivo

Completar F05/F06 para inspecionar estruturas de dados C sem confundir endereço,
valor e localização de variável.

### Entregas

1. Ampliar fixtures reais dos registros CDB `T:`.
2. Validar aliases, arrays, ponteiros, structs aninhadas e dependências entre
   tipos.
3. Formalizar `LValue`, endereço e valor escalar no avaliador.
4. Implementar:
   - `*p`;
   - `&x`;
   - `a[i]`;
   - `s.f`;
   - `p->f`.
5. Usar tamanho do elemento, offset do campo e largura do ponteiro Z80 a partir
   de evidência tipada.
6. Integrar macros com a gramática ampliada sem executar código do programa.
7. Validar ABI de `float` antes de inferir o tipo SDCC como `f32`.

### Critérios de conclusão

- Endereço e valor nunca são intercambiados implicitamente.
- Campo ou layout não comprovado retorna indisponibilidade explícita.
- Tipos com a mesma grafia em imagens diferentes preservam identidade.
- Testes cobrem frames vivos, callers, globais, statics e erros de tipo.
- A calculadora F17/F18 mantém a semântica atual.

### Dependências

Fase 7, especialmente manifesto, contexto de macros e headers.

## Fase 9 — Controle avançado de execução

**Estado:** concluída. F07–F10 estão implementados e validados offline;
breakpoint condicional, watchpoints read/write e breakpoint qualificado também
foram validados no openMSX 21.0.

### Objetivo

Adicionar controle condicionado sem expor Tcl arbitrário ou enfraquecer a
limpeza e a certeza de efeitos.

### Entregas

1. `continue --until-signature`
   - invocação explícita;
   - timeout e limite de tentativas;
   - interrupção confirmada ao atingir o limite.
2. Breakpoints condicionais
   - predicados tipados;
   - tradução controlada para openMSX;
   - listagem textual e JSON.
3. Breakpoints por slot/mapper
   - página, slot e segmento explícitos;
   - condição aplicada no alvo no momento do disparo.
4. Watchpoints
   - read, write e access;
   - faixa validada antes da criação;
   - propriedade, suspend/resume e limpeza.
5. Detecção de capacidades por versão/comportamento, sempre read-only antes de
   habilitar extensões.

### Critérios de conclusão

- Nenhuma condição aceita Tcl fornecido diretamente pelo usuário.
- Timeout após mutação nunca provoca retry automático.
- Breakpoints/watchpoints externos são preservados.
- Todos os ids próprios são rastreados e a limpeza tenta remover cada um mesmo
  após falha intermediária.
- Hardware sem capacidade retorna erro explícito.

### Dependências

Fase 7 para assinatura e segurança; fase 8 quando condições usarem valores C.

## Fase 10 — Áreas, imagens e mutações seguras

**Estado:** concluída e validada offline. Escritas live permanecem opt-in e
exigem um alvo explicitamente preparado.

### Objetivo

Ampliar a resolução contextual e introduzir escritas somente depois que o
modelo de estado e invalidação estiver totalmente demonstrado.

### Entregas

1. Resolver `_HOME`, `_GSINIT` e, quando houver evidência, `_GSFINAL`.
2. Resolver statics sem CDB apenas quando área e relocação forem demonstráveis.
3. Selecionar imagem pelo mapeamento ativo quando configuração e evidência forem
   suficientes; manter ambiguidade nos demais casos.
4. Escrita de memória
   - alvo parado;
   - largura, faixa e endianness validados;
   - leitura de verificação;
   - resultado parcial ou incerto explícito.
5. Escrita de registradores
   - larguras e registradores graváveis;
   - pares/metades coerentes;
   - releitura e nova geração de snapshot.
6. Invalidar caches e assinatura após toda mutação relevante.

### Critérios de conclusão

- Nenhuma escrita acontece como efeito colateral de `print`, `info` ou resolve.
- Falhas parciais não são anunciadas como sucesso e não prometem rollback.
- Seleção por mapper usa associação configurada, nunca coincidência de endereço.
- Resolução offline continua funcional sem emulador.

### Dependências

Manifesto da fase 7, tipos da fase 8 e capacidades investigadas na fase 9.

## Fase 11 — Produto, compatibilidade e release

**Estado:** concluída e validada offline. A qualificação live e a captura de
baseline em projeto real permanecem passos explícitos do checklist de cada
release candidate, pois dependem de um openMSX e artefatos preparados pelo
operador.

### Objetivo

Transformar o núcleo validado em uma distribuição reproduzível e sustentável.

### Entregas

1. `pyproject.toml`, entry point `msxdbg` e dependências versionadas.
2. Matriz CI para versões Python suportadas.
3. Separação formal entre testes unitários, cenários e live opt-in.
4. Guia de instalação, attach, troubleshooting e segurança.
5. Compatibilidade documentada por versão do openMSX e SDCC/SDLD.
6. Benchmarks reproduzíveis de attach, step, memória e carga de projetos reais.
7. Redução ou agregação de diagnósticos repetitivos em grandes projetos, sem
   ocultar origens relevantes.
8. Política de schema JSON e compatibilidade semântica.
9. Preparação de changelog e release candidate.

### Critérios de conclusão

- Instalação limpa fornece o comando `msxdbg` sem manipular `PYTHONPATH`.
- Suíte offline passa em CI; live continua explicitamente opt-in.
- Documentação reproduz os fluxos validados da fase 6.
- Desempenho possui baseline e limites, não apenas impressão subjetiva.
- Release candidate não contém stubs em comandos anunciados como disponíveis.

## Dependências resumidas

```text
Fase 7: serviços básicos e configuração
   ├── Fase 8: tipos e expressões C
   │      └── Fase 9: condições que consultam valores C
   ├── Fase 9: assinatura, breakpoints e watchpoints
   └── Fase 10: imagens, áreas e escritas
             └── Fase 11: distribuição e release
```

Fases 8 e 9 podem avançar parcialmente em paralelo depois da fase 7, desde que
não compartilhem contratos ainda indefinidos. A fase 10 deve preservar as
garantias de certeza e invalidação construídas nas fases anteriores.

## Próxima ação recomendada

Iniciar a fase 7 por `SourceRepository`, porque ele desbloqueia navegação de
fonte e o comando `list` sem exigir mutações no alvo. Em seguida implementar
`SafetyGate`/`SignatureGuard`, `MemoryMapService`, headers/macros e finalmente o
manifesto `--project`.
