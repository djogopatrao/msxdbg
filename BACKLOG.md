# msxdbg — Backlog de funcionalidades e requisitos

Análise da [SPEC.md](SPEC.md), especialmente §§7–8, complementada pelo §12 de [COMMANDS.md](COMMANDS.md), pela [arquitetura](ARCHITECTURE.md) e pelo [desenho dos módulos](MODULE_DESIGN.md).

Este backlog registra trabalho futuro; nenhum item está implementado neste diretório. Prioridades são propostas de ordenação, não datas de entrega. A inclusão de uma funcionalidade não torna sua sintaxe disponível. A SPEC permanece como referência histórica; este documento consolida os requisitos da evolução.

## 1. Classificação e prioridades

- **Planejado:** requisito já escolhido para a reescrita, ainda sem implementação.
- **Adiado:** requisito registrado para depois do núcleo compatível; contrato externo pode estar pendente.
- **Investigação:** depende de evidência técnica antes de comprometer comportamento.
- **Excluído:** incompatível com o escopo ou com as regras de segurança; não é tarefa de implementação.

**P1:** compõe a reescrita principal ou elimina uma limitação central. **P2:** extensão após os contratos básicos. **P3:** extensão posterior ou com incerteza relevante. P1 não implica que todos os itens pertençam ao primeiro incremento: a primeira entrega continua sendo resolução offline.

## 2. Índice de funcionalidades

| ID | Funcionalidade | Prioridade | Estado | Origem |
| --- | --- | --- | --- | --- |
| F01 | Modo não interativo e JSON | P1 | Planejado | SPEC §8.2.10 |
| F02 | Nomes C e seleção explícita de imagem | P1 | Planejado | SPEC §8.2.2, §7.2; ARCHITECTURE §4 |
| F03 | Configuração explícita multi-imagem | P1 | Planejado | SPEC B11; ARCHITECTURE §4 |
| F04 | Expressões completas e formato explícito de print | P1 | Planejado | SPEC §8.2.3 |
| F05 | Tipos de structs a partir do CDB | P1 | Planejado, condicionado a fixtures | SPEC §8.2.1 |
| F06 | Expressões C tipadas: ponteiros, arrays e campos | P2 | Adiado | SPEC §8.2.3 |
| F07 | Execução até reconhecimento de assinatura | P2 | Adiado | SPEC §8.3; COMMANDS §12 |
| F08 | Breakpoints condicionais | P2 | Adiado | SPEC §8.3; COMMANDS §12 |
| F09 | Breakpoints qualificados por slot/mapper | P2 | Adiado | SPEC §8.3 e exclusão inicial do §1; COMMANDS §12 |
| F10 | Watchpoints de memória | P2 | Adiado | SPEC §8.3; COMMANDS §12 |
| F11 | Resolução de código fora de `_CODE` | P2 | Adiado | SPEC §8.3 e §7.2 |
| F12 | Diagnóstico visível de conflitos de bases | P1 | Planejado | SPEC §8.3 |
| F13 | Seleção de imagem pelo mapeamento ativo | P3 | Investigação | SPEC §7.2; COMMANDS §12 |
| F14 | Escrita de memória | P3 | Adiado | SPEC §8.1; COMMANDS §12 |
| F15 | Escrita de registradores | P3 | Adiado | COMMANDS §12; extensão sem comando na SPEC |
| F16 | Leitura de statics sem CDB quando demonstrável | P3 | Investigação | Limitação da SPEC §7.2 |
| F17 | Print como calculadora, hex() e bin() | P1 | Planejado | Solicitação posterior do usuário; §8 deste documento |
| F18 | Macros de objeto e com parâmetros em print | P1 | Planejado | Solicitação posterior do usuário; §8 deste documento |

F09 e F13 são diferentes: o primeiro filtra disparos; o segundo escolhe a informação de programa correspondente aos bytes atualmente visíveis. F14 e F15 são requisitos novos de evolução, não capacidades já prometidas pela interface legada.

## 3. Requisitos funcionais detalhados

### F01 — Modo não interativo e JSON

Executar uma sequência de comandos no mesmo contexto de sessão, usando `msxdbg exec ... -c '...' --json`, e emitir um envelope versionado por comando executado.

**Aceitação:** ordem determinística; parar no primeiro erro; stdout exclusivamente JSON Lines; erros estruturados e diagnósticos auxiliares em stderr; códigos de saída 0/1/2 conforme COMMANDS. Reset/load são recusados inclusive com `yes`. Toda execução tem prazo finito configurável, cancelamento e limpeza de breakpoints próprios; falha de limpeza resulta em saída não zero. Testes cobrem parada normal, erro intermediário, timeout e valores indisponíveis.

**Dependências:** Session, registro de comandos, renderização JSON e FakeTarget. **Contrato definido:** `--timeout` limita o lote inteiro, aceita segundos positivos e usa 30 segundos por padrão; `clear`, `reset` e `load` são recusados em lote com `command-not-available-in-batch` antes de qualquer efeito no target.

### F02 — Nomes C e seleção explícita de imagem

Aceitar nomes C sem o `_` do linker e permitir qualificação `imagem::simbolo` e `imagem::arquivo:linha` nos resolvedores documentados.

**Aceitação:** nome exato precede alias; colisões retornam candidatos; duas funções estáticas homônimas não se sobrescrevem; caminhos são comparados por componentes; linha sem código informa a linha efetiva. Qualificar imagem não restringe mapper. A sintaxe offline de resolve e a gramática de expressões só são ampliadas quando documentadas explicitamente.

**Dependências:** identidades compostas e índices por imagem. Candidatos ainda ambíguos dentro da mesma imagem devem ser reportados; seleção por módulo poderá exigir uma sintaxe adicional, a definir sem escolher o primeiro resultado.

### F03 — Configuração explícita multi-imagem

Associar cada imagem aos seus próprios diretórios, maps e CDBs por `--project FILE`, com manifesto JSON versionado. Processar todos os CDBs associados, preservando suas origens.

**Aceitação:** caminhos relativos ao manifesto; ids únicos; descoberta determinística; erros úteis para overrides sem associação; fixture de residente e DLL compartilhando nomes de módulo. Preservar configuração simples por `--out`. Não aplicar silenciosamente uma lista de maps/CDBs a todas as imagens.

**Dependências:** ProjectSpec e loader. **Pendente:** esquema externo final e regras de combinação com opções CLI.

### F04 — Expressões completas e formato explícito

Analisar argumentos completos com espaços e precedência aritmética, oferecendo `print/TIPO EXPRESSÃO` e mantendo o tipo final legado quando inequívoco. `info symbol` também deve consumir a expressão completa.

**Aceitação:** `print/u16 hl + 3` lê o endereço correto; `(hl+3)*(hl)` não perde delimitadores; divisão negativa trunca em direção a zero; tipos ambíguos geram erro com orientação. Preservar leituras legadas com tipo explícito; F17 redefine expressões numéricas sem tipo como cálculos e preserva valor direto de registrador. Não introduzir execução de código Python nem casts C implicitamente.

**Dependências:** tokenizer, AST, parser e avaliador. Parte deste item corrige B1/B2; não duplicar a implementação como duas tarefas separadas.

### F05 — Tipos provenientes do CDB

Interpretar registros `T:` e relacionar tipos às variáveis para reduzir dependência de headers fornecidos manualmente. Usar o parser de headers como fallback explícito.

**Aceitação:** fixtures reais de structs, arrays e referências a outros tipos; identidade preservada entre imagens; tamanhos e offsets demonstráveis; conflito CDB/header gera diagnóstico; registros não suportados não produzem layout presumido. Tipo inválido desabilita dependentes por valor, preservando tipos independentes.

**Dependências:** investigação T03, reconciliação CDB e TypeDef. A presença de um registro `T:` não basta para afirmar suporte a qualquer construção C.

### F06 — Expressões C tipadas

Suportar `*p`, `&x`, `a[i]`, `s.f` e `p->f` usando informação de tipo disponível. Distinguir endereço, valor escalar e localização de variável durante a avaliação.

**Aceitação:** indexação usa tamanho do elemento; campo usa offset comprovado; acesso indireto respeita largura do ponteiro Z80; erros de tipo/localização são explícitos; operandos podem ser variáveis CDB no frame escolhido. `&x` produz endereço como valor, sem leitura acidental nesse endereço. Preservar o significado das formas legadas de print e testar conflitos entre indexação MAP explícita e indexação C tipada.

**Dependências:** F04, F05 e localização de variáveis. **Pendente:** formalizar a gramática combinada e os formatos de saída antes de ampliar COMMANDS como sintaxe aceita.

### F07 — Continuar até assinatura

Adicionar a forma proposta `continue --until-signature` para ignorar paradas anteriores ao carregamento, mediante solicitação explícita. Exige assinatura configurada, prazo finito e limite de tentativas.

**Aceitação:** parar no primeiro stop em que a assinatura corresponda; não retomar depois disso; se já verificada, retornar o estado atual sem continuar; sem configuração, rejeitar antes de executar. Ctrl-C, timeout, desconexão ou erro interrompem o fluxo e têm resultado explícito. Ao atingir limite, solicitar parada e só reportar registradores após confirmação. Não executar reset/load, não iniciar emulador e não habilitar esse comportamento no continue comum.

**Dependências:** SignatureGuard, ExecutionController e F01 para uso em lote. **Limite:** a primeira versão verifica a assinatura em paradas; se nenhuma parada ocorrer, o timeout encerra a espera. Monitoramento periódico durante execução seria requisito adicional.

### F08 — Breakpoints condicionais

Permitir que um breakpoint dispare somente quando um predicado suportado for verdadeiro, traduzindo-o pelo adaptador openMSX. A sintaxe de CLI e a gramática de condições ainda serão definidas.

**Aceitação:** condições verdadeiras/falsas verificadas em testes; condição inválida é rejeitada antes da criação; suspend/resume preservam condição; listagem e JSON a apresentam; exclusão/limpeza obedecem à propriedade dos ids. Timeout não provoca criação duplicada. Não expor Tcl arbitrário como linguagem de condições: usar representação tipada de predicados e tradução controlada.

**Dependências:** investigação T06 e extensão de BreakpointRecord/Target. Comparações sobre registradores/memória devem ter semântica e custos definidos antes da implementação; não reutilizar a AST aritmética sem especificar operadores e acesso à memória.

### F09 — Breakpoints qualificados por slot/mapper

Estender breakpoints com requisitos de página, slot e/ou segmento, como o caso “página N contém segmento S”, sem alterar o significado do breakpoint simples por endereço.

**Aceitação:** mesmo endereço em dois segmentos só dispara sob o qualificador configurado; valores de página/slot/segmento são validados contra capacidades conhecidas; erro explícito em hardware não suportado; configuração sobrevive a suspend/resume. A condição é aplicada no alvo no momento do disparo, não apenas conferida pela UI depois da parada.

**Dependências:** F08 e T06. Esse item relaxa apenas a exclusão inicial de breakpoints por segmento da SPEC; não relaxa attach-only. A seleção por nome de imagem não inventa automaticamente o segmento exigido.

### F10 — Watchpoints de memória

Permitir interrupção por leitura, escrita ou acesso em uma faixa de memória correspondente a endereço, global ou static com localização fixa conhecida.

**Aceitação:** resolver endereço/tamanho antes de armar; rejeitar faixa inválida, símbolo ambíguo ou static sem localização demonstrável; indicar tipo de acesso e faixa em texto/JSON; permitir listar, suspender, retomar e excluir; limpar somente watchpoints próprios. Tipo pode fornecer tamanho; caso contrário, exigir tamanho explícito. Testes distinguem write/read/access e acesso fora da faixa.

**Dependências:** T06 e novo contrato tipado de watchpoints no Target/Session. Não assumir que a sintaxe remota citada na SPEC é compatível com toda versão instalada. Locais de stack, variáveis em registradores e condições por segmento ficam fora do primeiro incremento de watchpoints. Número remoto, namespace de números locais e comandos ficam pendentes de desenho.

### F11 — Resolução de áreas adicionais

Resolver `_HOME` e `_GSINIT`; avaliar `_GSFINAL` como extensão do mesmo trabalho quando os artefatos permitirem. Não confundir áreas de código e dados.

**Aceitação:** relocação por módulo e área, com intervalos demonstráveis; teste de offsets iguais em áreas diferentes; resolve, break por linha, stop report e disassembly utilizam a mesma localização. Área sem evidência suficiente permanece não resolvida com diagnóstico. Não usar símbolo público mais próximo para decidir propriedade.

**Dependências:** loader multiárea e fixtures SDCC/linker. `_GSFINAL` é derivado da limitação de §7.2, não compromisso de suporte sem evidência.

### F12 — Conflitos de bases visíveis

Expor `base_conflicts` na carga e no resultado diagnóstico do projeto, com módulo, área, bases candidatas e artefatos de origem.

**Aceitação:** avisos textuais no início da sessão e diagnósticos estruturados acessíveis ao modo de agentes; não poluir stdout JSON; empate sem evidência não escolhe base; maioria conflitante preserva a ressalva nas resoluções afetadas. Fixture sem conflito não recebe aviso.

**Dependências:** Diagnostic e loader. O cálculo de candidatos existente não conta como entrega até o usuário conseguir inspecionar a incerteza.

### F13 — Seleção de imagem pelo mapeamento ativo

Investigar e implementar, quando demonstrável, resolução de PC/símbolos usando slot e segmento observados junto ao contexto da parada.

**Aceitação:** configuração associa explicitamente imagens/regiões a mapeamentos; duas imagens no mesmo endereço são distinguidas quando há evidência suficiente; sem associação, manter ambiguidade; mudança de mapper invalida caches relevantes; resolução offline continua disponível sem emulador. Snapshot registra a evidência usada, com limites de consistência externa documentados.

**Dependências:** F03, capacidades de páginas e modelo adicional de associação entre imagem e memória. Leitura de segmento sozinha não revela qual binário está carregado; não inferir identidade só pela coincidência de endereço.

### F14 — Escrita de memória

Adicionar operação explícita para escrever bytes ou valor escalar com tipo definido em endereço resolvido. A interface atual permanece somente de leitura até a definição do comando.

**Aceitação:** exigir alvo parado; validar endereço, tamanho, faixa, largura e endianness antes de escrever; não envolver silenciosamente em 0xFFFF; invalidar snapshot/caches antes da mutação e reconstruir por leitura confirmada. Leitura de verificação informa bytes divergentes e possível escrita parcial; timeout não repete automaticamente. Expor falha de região ROM/não gravável sem afirmar sucesso. Escrita na faixa da assinatura rearma o guard.

**Dependências:** nova API write_memory, FakeTarget mutável, política de efeitos da sessão e definição de sintaxe. Leituras/escritas com efeitos de hardware devem ser explicitadas no contrato; não prometer rollback. Uso em exec só por comando explícito, nunca como efeito colateral de print/eval.

### F15 — Escrita de registradores

Adicionar atribuição explícita de valor a registrador suportado, incluindo regras para metades e pares, com validação de largura.

**Aceitação:** exigir alvo parado; registradores não graváveis retornam erro; metade atualiza somente os bits correspondentes; valores fora da largura são rejeitados; PC/SP/IX invalidam seleção de frame e toda inspeção derivada. Após escrita, reler registradores e publicar nova geração de estado; não continuar CPU automaticamente. Timeout deixa resultado incerto, sem retry de mutação.

**Dependências:** nova API write_register, T06 para capacidades, testes FakeTarget e sintaxe a definir. Não disponibilizar chamadas Tcl genéricas como atalho.

### F16 — Statics sem CDB

Investigar resolução de endereço de labels estáticos a partir de área, base ligada e listing, mesmo sem informação CDB.

**Aceitação:** permitir leitura somente quando endereço e área puderem ser demonstrados; exigir tipo explícito quando não houver tipo; símbolos homônimos mantêm qualificação/ambiguidade; ausência de evidência preserva a nota explicativa atual. Não tratar offset local como endereço absoluto nem prometer leitura de locais automáticos sem debug info.

**Dependências:** F11 quando a área não for `_CODE`, e evidência nos artefatos. Se o linker não fornecer dados suficientes, registrar o limite em vez de implementar heurística silenciosa.

## 4. Melhorias técnicas e investigações

Estes itens habilitam funcionalidades ou aumentam confiabilidade, mas não são novos comandos.

| ID | Trabalho | Critério de conclusão | Dependências/consumidores |
| --- | --- | --- | --- |
| T01 | Conexão persistente | **Implementada com sondagem read-only, métricas de conexões e fallback per-command; validação live opt-in disponível.** Múltiplos comandos, XML fragmentado/eventos e perda de conexão cobertos; sem retry de mutações | Target/transport |
| T02 | Leitura em bloco e strings progressivas | **`debug read_block` implementado atrás de capability, com hex binário-seguro e comparação live opt-in contra fallback.** Strings progressivas continuam incremento separado | print, memória, frames |
| T03 | Fixtures e gramática CDB T | Coleção real com compilador/flags e catálogo de construções suportadas/rejeitadas | F05/F06 |
| T04 | ABI de float Z80 | Fixture compilada com valores conhecidos; verificar bytes e documentar interpretação | f32/inferência de tipos |
| T05 | Frames, epílogos e limites de função | Fixtures de múltiplos retornos e função sem exit marker; recusa explícita onde não há prova | backtrace, locals/args |
| T06 | Capacidades openMSX para condições, watchpoints, mapper e escrita | Validar comandos e comportamento em ambiente preparado; documentar versões/capacidades e falhas | F08–F10, F13–F15 |
| T07 | Cache por parada e custos de inspeção | Invalidar em retomada/reset/load/reconexão/escrita; medir chamadas repetidas; nenhuma leitura obsoleta | Session/Evaluator |
| T08 | Integração opt-in com openMSX | Programa isolado e ambiente preparados pelo operador; cenários sem boot/reset/load automático | Validação dos caminhos live |

T01/T02/T06 não autorizam iniciar emulador ou preparar mídia automaticamente. Ensaios de escrita/controle exigem ambiente de teste explicitamente preparado para essas operações.

## 5. Correções obrigatórias do núcleo

Os bugs B1–B11 continuam requisitos de qualidade da reescrita, não funcionalidades adiadas:

| Bugs | Entrega correspondente |
| --- | --- |
| B1/B2 | Parser completo de expressões e argumentos (F04) |
| B3 | Limpeza dos breakpoints próprios e relato honesto de falhas |
| B4 | Resolução de arquivos por componentes e ambiguidade explícita (F02) |
| B5/B6 | Identidades compostas e chaves corretas de cache |
| B7 | finish aguarda parada confirmada |
| B8 | disassemble aceita símbolos pelo resolvedor tipado |
| B9 | Registro único gera help/completion incluindo aliases |
| B10 | Escape XML e quoting Tcl corretos e separados |
| B11 | Associação por imagem e todos os CDBs pertinentes (F03) |

Não adiar correções de segurança/consistência para implementar novos comandos. Quando um bug e uma funcionalidade compartilham implementação, manter uma entrega e rastrear ambos os requisitos.

## 6. Tratamento completo do item 12 de COMMANDS

| Item anteriormente sem sintaxe | Destino |
| --- | --- |
| Escrita de memória | F14, adiado |
| Escrita de registradores | F15, adiado |
| Watchpoints | F10, adiado |
| Condições de breakpoint | F08, adiado |
| Qualificação por mapper | F09, adiado; ligada à SPEC §8.3 |
| Seleção automática por mapper | F13, investigação |
| `continue --until-signature` | F07, adiado; somente invocação explícita e limitada |
| Gerenciamento de mídia | X01, excluído |
| Inicialização do emulador | X02, excluído |

**X01 — Mídia/boot/velocidade:** não adicionar inserção/troca de disco, boot automático ou alteração de velocidade. **X02 — Ciclo de vida do emulador:** não iniciar, reiniciar processo ou encerrar openMSX; somente conectar/desconectar o cliente. Reset interativo explicitamente confirmado continua sendo a operação existente, não gerenciamento automatizado do processo.

VRAM e BASIC também permanecem excluídos conforme SPEC §1. Reset/load exigem confirmação humana literal por operação e nunca são permitidos em automação. Não há requisito para bypass de segurança. O usuário solicitar documentação de backlog não revoga essas restrições.

## 7. Impacto nos módulos e promoção de requisitos

O [TEST_PLAN.md](TEST_PLAN.md) rastreia os requisitos em cenários por função e módulo e reserva testes para funcionalidades adiadas sem pressupor APIs já implementadas.

| Grupo | Módulos a evoluir |
| --- | --- |
| F17/F18 | eval/tokens, macros, ast, parser, evaluator, values; debuginfo/macros e loader; renderizadores |
| F01/F04 | ui/registry, commands, batch, render_json; eval/parser/evaluator |
| F02/F03/F05/F11/F12/F16 | debuginfo/model, loader, parsers e index; ui para diagnósticos |
| F06 | eval/ast, parser, evaluator, values; InspectionContext |
| F07 | session/execution, safety e resultados; opções do comando continue |
| F08/F09 | Predicados tipados em target/api; breakpoint records e adapter; comandos/JSON |
| F10 | Contratos próprios de watchpoints em target e session; registro de comandos e limpeza |
| F13 | Modelo de associação de imagens e mapeamento; snapshots e resolução contextual |
| F14/F15 | Target, FakeTarget, Session, invalidação e novos handlers explícitos |

As assinaturas atuais de MODULE_DESIGN descrevem o núcleo; capacidades adiadas não devem aparecer como métodos já disponíveis. Antes de iniciar cada extensão: resolver pendências de sintaxe/capacidade, atualizar contratos e COMMANDS, definir fixtures e implementar critérios de aceitação. APIs futuras não são substituídas por um escape genérico de Tcl.

Ordem sugerida após o núcleo: concluir F01–F05/F12 e integrar F17/F18 conforme marcos da arquitetura; depois F06/F11 e F07; em seguida F08→F09 e F10; avaliar F13–F16 após as investigações. Funcionalidades independentes podem mudar de ordem conforme necessidade real, preservando dependências e restrições.

## 8. Novos requisitos solicitados: calculadora e macros

Os requisitos F17/F18 foram solicitados após o backlog inicial e têm prioridade P1, estado **Planejado**. Refinam F04 e substituem a regra anterior de que toda expressão numérica de print representa endereço. São requisitos da reescrita, ainda não implementados.

### F17 — Print como calculadora, com hex() e bin()

`print EXPRESSÃO`, sem tipo explícito e sem colchetes externos, avalia uma expressão aritmética e apresenta seu resultado. `hex(expr)` e `bin(expr)` são funções internas de apresentação de inteiros; não chamam funções Z80 ou Python. A sintaxe e a compatibilidade estão detalhadas no §8 de COMMANDS.

**Aceitação:** `print 2 + 3 * 4` resulta em 14; `print (2 + 3) * 4` resulta em 20; `print hex(255)` exibe `0xff`; `print bin(10)` exibe `0b1010`. Resultados não sofrem truncamento de 16 bits (`print 65535 + 1` resulta em 65536). Divisão inteira trunca em direção a zero; divisão por zero e número errado de argumentos produzem erros claros. Sinal negativo é preservado, sem largura implícita de complemento de dois. Chamadas aninhadas preservam o valor inteiro: `print hex(bin(10) + 1)` exibe `0xb`; somente chamada externa hex/bin determina formato da saída.

**Compatibilidade:** `print [expr] u16` e `print/u16 [expr]` leem memória; manter `print 0xC000 u16` e `print/u16 hl + 3` como leituras legadas com tipo explícito. Símbolo MAP isolado e variável CDB isolada preservam suas leituras legadas; em aritmética, símbolo MAP representa endereço, variável CDB tipada representa valor, registrador representa seu valor. Parênteses passam a ser agrupamento na calculadora; `print (hl)` calcula HL. Para forçar leitura sem tipo, usar `print [hl]`. A migração deve ser anunciada, sem heurística baseada no valor numérico.

**Dependências:** F04 e extensão dos resultados/AST. Cálculos só com constantes/macros constantes não consultam Target e podem executar na sessão mesmo sem parada confiável. Expressões com registradores/variáveis/memória exigem o contexto correspondente. JSON preserva valor numérico e inclui formato solicitado, não substitui valor por string formatada.

### F18 — Expansão de macros em print

Aceitar macros de objeto e macros com parâmetros nas expressões, incluindo os pedidos `print [0x8000+MY_OFFSET] u16` e `print NLV( _g_teste,_g_outro_teste)`. A definição de NLV vem do projeto; seu significado não é deduzido do nome.

**Aceitação:** com `#define MY_OFFSET 0x20`, o primeiro exemplo lê u16 em 0x8020. Com a definição de teste `#define NLV(a,b) ((a)+(b))`, a segunda forma calcula a soma dos endereços MAP dos dois símbolos. Essa definição é apenas fixture, não macro predefinida. Uma macro real pode exigir operadores tipados de F06; construções fora da gramática habilitada recebem diagnóstico específico, nunca valor presumido.

Expandir tokens antes de construir a AST, respeitando parâmetros, vírgulas e parênteses aninhados; não adicionar parênteses que alterem o significado do texto da macro. Macros de objeto encadeadas e funções com argumentos que também contenham macros devem funcionar. Validar aridade; preservar origem e cadeia de expansão nos erros; detectar ciclos e limitar profundidade/tamanho. Expansão não executa comandos, não modifica memória e não chama funções do programa. Chamadas remanescentes só podem ser hex/bin ou operadores explicitamente suportados; nomes hex/bin são reservados à apresentação e conflito de macro é diagnosticado.

**Origem e contexto:** definições são indexadas por imagem/unidade de compilação com arquivo/linha e tokens originais. Usar fontes/headers explicitamente carregados e metadados de compilação quando disponíveis; aproveitar headers fornecidos por `--struct-header` sem executar ferramentas externas. CDB não é presumido como catálogo completo de macros. Definições condicionais, includes e flags só podem ser consideradas resolvidas com contexto de pré-processamento conhecido; caso contrário, registrar dependência não suportada/ambiguidade. Nunca selecionar silenciosamente a primeira definição homônima ou coletar todos os ramos de um `#if` como ativos.

A primeira implementação aceita o subconjunto demonstrável de `#define NAME tokens` e `#define NAME(args) tokens`, incluindo continuação de linha. Stringification `#`, token pasting `##`, macros variádicas, efeitos de `#undef`/redefinição sem contexto e pré-processamento C completo ficam fora desse incremento e exigem erro explícito quando necessários. Não prometer avaliar toda macro C arbitrária. Entrada por arquivo dedicado de macros e configuração de include paths/flags precisam de sintaxe externa definida antes da implementação.

**Dependências:** F04/F17, catálogo de macros e expander de tokens; F06 para corpos que usem campos/ponteiros. Testar expansão fora de parada para constantes, macro inexistente, colisão entre imagens, ciclo, argumentos aninhados, `#if` indeterminado, precedência textual e limite de recursos.
