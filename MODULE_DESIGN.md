# msxdbg — Projeto dos módulos e contratos públicos

Proposta anterior à implementação, baseada em [SPEC.md](SPEC.md), [ARCHITECTURE.md](ARCHITECTURE.md) e [COMMANDS.md](COMMANDS.md). Define responsabilidades, dados, interfaces e colaboração; não afirma que essas classes já existem. Métodos privados, algoritmos internos e subdivisões de arquivos podem evoluir sem alterar os contratos aqui descritos.

## 1. Convenções e regras de dependência

As assinaturas são esquemáticas, compatíveis com Python 3.9: usam `Optional`, `Union`, `Protocol` e genéricos de `typing`. Imports e construtores triviais de dataclasses são omitidos. Tipos citados nas tabelas pertencem ao módulo daquela seção, salvo indicação explícita.

- DTOs de resultado são dataclasses imutáveis; coleções expostas são tuplas ou mappings somente de leitura.
- Serviços com estado declaram seu proprietário e ciclo de vida. Não há singletons, registradores globais mutáveis ou acesso implícito ao target.
- APIs são síncronas na primeira versão. Há no máximo uma operação de controle em andamento.
- Parsers e renderizadores não fazem controle de execução. Renderizadores também não leem o target.
- `ui → eval → session`; `ui → session`; `eval/session → debuginfo`; `session → target.api`. `debuginfo` não importa essas camadas. `target` não importa informação de programa.
- `session` nunca importa `eval` ou `ui`. Leitura para avaliação passa pelo protocolo `InspectionContext` da sessão.
- Exceções representam operação inválida ou falha operacional. Ausência, ambiguidade e valor indisponível esperados são resultados tipados.

A árvore da arquitetura inclui `session/results.py` para resultados de casos de uso, `ui/results.py` para envelopes e os dois módulos de macros descritos no §13. Esses módulos não criam uma camada genérica compartilhada entre os pacotes.

## 2. Tipos fundamentais e propriedade do estado

| Conceito | Contrato |
| --- | --- |
| Endereço CPU | Inteiro validado entre 0 e 65535; só o avaliador aritmético aplica máscara de compatibilidade |
| Intervalo | `AddressRange(start, end_exclusive)`; permite limite final 65536, não permite inversão ou wrap |
| Leitura que atravessa 0xFFFF | API Target rejeita; um chamador que necessite wrap deve dividi-la explicitamente |
| Identidade | Inclui imagem e módulo; nomes de funções sozinhos não são chaves |
| Origem | Arquivo de artefato, linha física e espécie de registro |
| Resultado de consulta | `Resolution[T]`: `unique`, `missing` ou `ambiguous`; nunca primeiro candidato implícito |
| Disponibilidade | Valor conhecido ou motivo estruturado de indisponibilidade; desconhecido não é zero |
| Geração | `stop_id` identifica parada; `memory_epoch` identifica invalidação de análises do código |

| Estado mutável | Proprietário | Duração/invalidação |
| --- | --- | --- |
| Projeto e índices | `ProjectLoader`, depois leitura por `Project` | Uma carga; recarga cria novo projeto |
| Socket e parser XML | `OpenMSXTransport` | Conexão; descartado em erro de protocolo |
| Execução e snapshot | `Session` | Sessão; snapshot invalidado antes de retomar |
| Cache de memória e frames | `StopCache` interno à sessão | Uma parada |
| Breakpoints próprios | `BreakpointManager` | Sessão; preserva falhas pendentes de reconciliação |
| Autorizações especiais | `SafetyGate` | Uma tentativa autorizada, sem reutilização |
| Navegação de list/disas | `NavigationState` na UI | Sessão de UI, independente da seleção de frame |
| Histórico e repetição | `Repl` | Sessão interativa; reset/load não entram na repetição |

Não se garante detecção de outro cliente que execute e pare a CPU entre duas consultas. A consistência é verificada nas fronteiras observáveis, sem prometer atomicidade do protocolo.

## 3. `debuginfo`: informação offline

### 3.1 `debuginfo/diagnostics.py`

| Tipo | Campos/finalidade |
| --- | --- |
| `Origin` | `path: Path`, `line: Optional[int]`, `record_kind: str` |
| `Diagnostic` | `code`, `severity`, `message`, `origins: tuple[Origin, ...]` |
| `ParseResult[T]` | `value: T`, `diagnostics: tuple[Diagnostic, ...]` |
| `ProjectLoadError` | Carga inviável; contém diagnósticos completos |

Registros isolados inválidos geram diagnósticos e permitem continuar quando seguro. Erros de arquivo essencial impedem a carga; erro de tipo opcional desabilita apenas o tipo dependente. Nenhuma função imprime.

### 3.2 `debuginfo/model.py`

| Classe | Campos públicos essenciais |
| --- | --- |
| `ImageId` | Valor textual estável na configuração |
| `ModuleId` | `image: ImageId`, `key: str` |
| `FunctionId` | `module: ModuleId`, `record_identity: str` |
| `VariableId` | `module: ModuleId`, `record_identity: str` completa, incluindo escopo |
| `TypeId` | Imagem/módulo opcionais para primitivos, identidade do tipo |
| `AddressRange` | `start`, `end_exclusive` |
| `SourceSpan` | Caminho original, normalizado, linha, texto opcional |
| `Symbol` | Nome ligado, endereço, módulo opcional, origem; preserva pseudo-símbolos de área |
| `Area` | Nome, base opcional, limite opcional, evidências |
| `Module` | Id, nome, áreas, labels, exports e linhas |
| `Function` | Id, nome, entry, end opcional, proveniência do limite, linhas e blocos |
| `Variable` | Id, nome, função opcional, bloco, tipo, storage, classificação de parâmetro |
| `TypeDef` | Id, nome, categoria, tamanho opcional, sinal, tipo referenciado e campos |
| `Field` | Nome, TypeId, offset; contagem de array pertence ao tipo array |
| `Storage` | União de `AbsoluteStorage`, `StackStorage`, `RegisterStorage`, `UnknownStorage` |
| `CodeLocation` | Imagem, módulo, área, endereço, offset, fonte e função opcionais, evidências |
| `Image` | Id e coleções reconciliadas de módulos, símbolos, funções, variáveis, tipos e diagnósticos |
| `Resolution[T]` | Status, candidatos, diagnósticos; único tem exatamente um candidato |

`StackStorage` armazena offset canônico CDB; não calcula endereço usando SP/IX. `RegisterStorage` preserva ordem dos bytes de menor para maior peso. `TypeDef` usa referências por id para suportar grafos de tipos; ciclos por ponteiro são permitidos, ciclos de composição por valor são inválidos.

```python
class AddressRange:
    def contains(self, address: int) -> bool: ...

class Resolution(Generic[T]):
    def unique_or_none(self) -> Optional[T]: ...
```

`unique_or_none` não é usado para esconder ambiguidade na UI: o chamador deve conferir `status`. A resolução de símbolo mais próximo é separada da propriedade de módulo.

### 3.3 Parsers de artefatos

Parsers recebem texto por linhas, não abrem conexões e não decidem associação entre imagens. Os registros retornados conservam offsets e identidades originais; a relocação pertence ao loader/indexador.

```python
# debuginfo/map_parser.py
def parse_map(lines: Iterable[str], origin: Path) -> ParseResult[MapData]: ...
# debuginfo/lst_parser.py
def parse_lst(lines: Iterable[str], origin: Path) -> ParseResult[ListingData]: ...
# debuginfo/cdb_parser.py
def parse_cdb(lines: Iterable[str], origin: Path) -> ParseResult[CdbData]: ...
# debuginfo/header_parser.py
def parse_headers(inputs: Sequence[HeaderInput]) -> ParseResult[HeaderTypes]: ...
```

Todas as funções acima são funções de módulo.

| Módulo | Dados públicos próprios | Obrigações |
| --- | --- | --- |
| `map_parser.py` | `MapData(symbols)` | Tabelas `Value Global`, cabeçalhos repetidos, símbolos sem módulo |
| `lst_parser.py` | `ListingData(module_name, areas, labels, globals, lines)`, `ListingSymbol(name, area, offset, origin)`, `ListingLine(area, offset, source, origin)`; export declarado tem offset desconhecido (`None`) | Colunas fixas, linha C pendente, áreas reentrantes, primeiro offset vence |
| `cdb_parser.py` | `CdbData(functions, symbols, links, lines, types, modules)` com DTOs brutos `CdbFunction`, `CdbSymbol`, `CdbLink`, `CdbLine`, `CdbType`, `CdbModule` | Preservar identidades F/S/L/T, escopos, tipos codificados e alocações; formatos não suportados geram diagnósticos |
| `header_parser.py` | `HeaderInput(path, text)`, `HeaderTypes(types, macros)` | Gramática restrita de macros, rejeição por struct e propagação a dependentes |

A associação de `L:` a F/S ocorre após coletar os registros, inclusive quando estiverem em arquivos diferentes da mesma imagem. O parser de headers não importa o avaliador de expressões do debugger: sua gramática de constantes é pequena, privada e sem registradores/símbolos vivos.

`parse_cdb` não fabrica ids de imagem, endereços de variáveis ou limites de função. `CdbIdentity` preserva scope/nome/level/sublevel/block e a identidade textual integral. `M:` é metadado, não mudança implícita de escopo; globals permanecem sem módulo atribuído. `CdbStorage` conserva código, on-stack, offset canônico, registradores na ordem original e eventual alocação alternativa. `CdbSymbol.is_temporary` marca `sloc<N>` para filtragem obrigatória pelo loader/indexador; parâmetros ainda não são inferidos.

Links F/S e marcadores X permanecem em `links`, sem classificação por formato do nome; o endereço X permanece inclusivo e sua ausência não vira limite estimado. Linhas C ficam em `lines`, com endereço e escopo; links A são ignorados. Registros repetidos são preservados com suas origens para reconciliação posterior. Tipos de declaração são cadeias opacas com tamanho/sinal; T aceita somente membros no formato demonstrado em `tests/fixtures/cdb/README.md` e nos testes D09. `CdbType` não é `TypeDef`: não certifica layout, tamanho, união versus struct ou grafo de referências.

### 3.4 `debuginfo/loader.py`

```python
class ImageSpec:
    id: ImageId
    out: Path
    maps: Optional[tuple[Path, ...]]
    cdbs: Optional[tuple[Path, ...]]

class ProjectSpec:
    images: tuple[ImageSpec, ...]
    source_roots: tuple[Path, ...]
    struct_headers: tuple[Path, ...]

class ProjectLoader:
    def discover(self, spec: ImageSpec) -> ImageArtifacts: ...
    def load(self, spec: ProjectSpec) -> LoadedProject: ...

def read_project_spec(path: Path) -> ProjectSpec: ...
```

`ImageArtifacts` contém paths descobertos por espécie; `LoadedProject` contém `project: Project`, `sources: SourceRepository`, `macros: MacroCatalog` e diagnósticos. `None` em maps/cdbs significa descoberta; tupla explícita substitui descoberta. Ids duplicados e overrides sem imagem definida falham antes do parsing.

O loader abre arquivos, chama parsers, reconcilia bases e CDBs, resolve tipos e cria índices. Conflitos majoritários de base são preservados; empate sem evidência suficiente não escolhe uma base arbitrária. O manifesto externo continua pendente de esquema final; `ProjectSpec` estabiliza o contrato interno sem antecipar opções de CLI.

Implementação atual: descoberta recursiva determinística sem seguir diretórios simbólicos; overrides `maps`/`cdbs` são paths fornecidos pelo chamador, e tuplas vazias desativam a descoberta daquela espécie. Cada imagem exige ao menos um MAP com símbolos utilizáveis. Artefatos descobertos/explicitados que não podem ser lidos falham com `ProjectLoadError`; registros inválidos continuam como diagnósticos dos parsers. CDB e LST ausentes permitem consultas MAP, sem inventar linhas ou funções.

A reconciliação privada em `_reconcile.py` reúne todos os CDBs da imagem, conserva conflitos e filtra `sloc`. Bases `_CODE` usam um voto por export; empate fica desconhecido. O limite LST `último offset + 16` é inclusivo e identificado como `lst-fallback`; a próxima base o limita. Fim CDB inclusivo é convertido para exclusivo; na ausência de exit, usa-se próxima entrada ou limites `s__CODE`/`l__CODE` comprovados. Sem essas provas, a última função só resolve nos endereços conhecidos, sem intervalo infinito. Linhas CDB válidas prevalecem sobre LST, com diagnóstico em divergências.

`_types.py` resolve primitivos Z80, ponteiros de dois bytes, arrays e o subconjunto packed de T demonstrado nos testes. Referências por ponteiro podem ser recursivas; composição por valor recursiva, sobreposição, padding não demonstrado e dependências inválidas ficam indisponíveis. Tipos e variáveis carregam evidências. O suporte a headers e macros não está implementado neste incremento: `struct_headers` gera `load.headers-unavailable` e a carga de código continua; `MacroCatalog` é entregue vazio. D12 permanece parcial quanto a esses serviços. `SourceRepository` também conserva seu contrato de stub.

### 3.5 `debuginfo/index.py`

`Project` é a fachada de consulta imutável, com índices privados por imagem.

```python
class Project:
    images: tuple[Image, ...]

    def resolve(self, address: int,
                image: Optional[ImageId] = None) -> Resolution[CodeLocation]: ...
    def resolve_line(self, path: str, line: int,
                     image: Optional[ImageId] = None) -> Resolution[LineMatch]: ...
    def lookup_symbol(self, name: str,
                      image: Optional[ImageId] = None) -> Resolution[Symbol]: ...
    def nearest_symbol(self, address: int,
                       image: Optional[ImageId] = None) -> Resolution[SymbolMatch]: ...
    def function_at(self, address: int,
                    image: Optional[ImageId] = None) -> Resolution[Function]: ...
    def find_variable(self, name: str,
                      context: SymbolContext) -> Resolution[Variable]: ...
    def variables_in_scope(self, context: SymbolContext,
                           kind: VariableKind) -> tuple[Variable, ...]: ...
    def lookup_type(self, name: str,
                    image: Optional[ImageId] = None) -> Resolution[TypeDef]: ...
    def type_by_id(self, id: TypeId) -> TypeDef: ...
    def completion_catalog(self) -> CompletionCatalog: ...
```

O modelo agora conserva `locations: tuple[CodeLocation, ...]` em `Image`, `Module` e `Function`; `Function.scopes` usa `BlockScope(level, sublevel, block, extent)`. `Area.limit_provenance` distingue limites estimados. `Variable` acrescenta escopo, level/sublevel e evidências; `TypeDef` acrescenta evidências. Coleções continuam imutáveis. Ausência de linhas completas de função não prova que uma variável seja parâmetro.

`LineMatch` inclui linha solicitada, linha efetiva e `CodeLocation`; `SymbolMatch` inclui símbolo e offset. `SymbolContext` contém imagem/módulo/função resolvidos e PC de escopo; contexto ambíguo não deve ser convertido silenciosamente numa imagem. `VariableKind` distingue locals/parameters/all. `CompletionCatalog` contém apenas metadados offline de nomes e arquivos.

Busca exata de símbolo precede alias sem `_`. `resolve_line` compara componentes de caminho e mantém todos os candidatos; o avanço para linha com código ocorre por arquivo candidato. Funções sem limite comprovado não recebem intervalo infinito. `variables_in_scope` mantém a regra documentada dos blocos de parâmetros e a exclusão antes da primeira linha executável.

### 3.6 `debuginfo/sources.py`

```python
class SourceRepository:
    def locate(self, source: SourceSpan) -> Resolution[Path]: ...
    def read_window(self, source: SourceSpan,
                    before: int, after: int) -> SourceWindow: ...
    def invalidate(self, path: Optional[Path] = None) -> None: ...
```

`SourceWindow` contém path, linhas numeradas, linha focal e diagnósticos. Prioridade: caminho absoluto, raízes configuradas, pais dos diretórios de listings. Arquivo indisponível permite texto de fallback do listing; erros não apagam a localização. Cache de fontes é independente de paradas e revalidado por metadados do arquivo.

## 4. `target`: operações do emulador

### 4.1 `target/api.py`

Tipos: `RegisterSet(values)` com acesso a pares e metades; `Instruction(address, size, text, raw_bytes)`; `PageState(page, primary_slot, secondary_slot, segment)`; `RemoteBreakpoint(id, address)`; `ExecutionStatus` (`running`, `stopped`); `TargetCapabilities` (persistência e leitura em bloco verificadas).

```python
class RegisterSet:
    def get(self, name: str) -> int: ...
    def width(self, name: str) -> int: ...

class Target(Protocol):
    def execution_status(self) -> ExecutionStatus: ...
    def read_registers(self) -> RegisterSet: ...
    def read_memory(self, address: int, size: int) -> bytes: ...
    def disassemble(self, address: int, count: int) -> tuple[Instruction, ...]: ...
    def read_pages(self) -> tuple[PageState, ...]: ...
    def continue_execution(self) -> None: ...
    def step_into(self) -> None: ...
    def step_over(self) -> None: ...
    def step_out(self) -> None: ...
    def run_to(self, address: int) -> None: ...
    def interrupt(self) -> None: ...
    def create_breakpoint(self, address: int) -> str: ...
    def remove_breakpoint(self, remote_id: str) -> None: ...
    def list_breakpoints(self) -> tuple[RemoteBreakpoint, ...]: ...
    def reset(self) -> None: ...
    def save_state(self, name: str) -> None: ...
    def load_state(self, name: str) -> None: ...
    def close(self) -> None: ...
```

Retorno `None` de controle confirma aceitação, nunca parada. Leitura retorna exatamente o tamanho solicitado ou erro; tamanho zero retorna bytes vazios. `close` é idempotente e não controla a CPU. Apenas a sessão recebe a instância com operações especiais; a UI e o avaliador não recebem `Target`.

Erros públicos: `TargetError`, `TargetUnavailable`, `TargetTimeout`, `TargetCommandError`, `TargetProtocolError`. Erros incluem operação e `outcome_unknown: bool`, distinguindo rejeição confirmada de mutação possivelmente aplicada. Não existe API pública de Tcl arbitrário.

### 4.2 `target/transport.py`

```python
class TransportConfig:
    socket_path: Path
    timeout_seconds: float
    connection_mode: ConnectionMode

class OpenMSXTransport:
    def request(self, tcl: str) -> TclReply: ...
    def drain_events(self) -> tuple[ProtocolEvent, ...]: ...
    def close(self) -> None: ...

def discover_socket(explicit: Optional[Path]) -> Path: ...
```

`ConnectionMode` é per-command ou persistent; persistent só após comprovação de capacidade. `TclReply` contém status e texto decodificado; `ProtocolEvent` é evento não solicitado. O transporte faz escape XML, framing incremental, timeout e validação de resposta. Não conhece nomes de registradores, tipos C nem significado do Tcl. Fila de eventos deve ter limite para evitar crescimento indefinido.

### 4.3 `target/openmsx.py`

```python
class OpenMSXTarget:
    def __init__(self, transport: OpenMSXTransport,
                 capabilities: TargetCapabilities) -> None: ...
    # Implementa integralmente Target.
```

Constrói Tcl com quoting correto, interpreta retorno e normaliza erros. Batch de registradores, memória em bloco/fallback e parsing de disassembly por colunas ficam aqui. Helpers de Tcl são privados. Detecção de capacidade usa somente operações de leitura; não testa reset/load nem outras mutações.

### 4.4 `target/fake.py`

```python
class FakeTarget:
    def __init__(self, memory: bytes, registers: RegisterSet,
                 script: Sequence[ScriptedEvent]) -> None: ...
    def inject_failure(self, operation: str, error: TargetError,
                       after_apply: bool = False) -> None: ...
    @property
    def calls(self) -> tuple[TargetCall, ...]: ...
    # Implementa integralmente Target.
```

`ScriptedEvent` descreve operações esperadas, transições de execução e novos registradores; `TargetCall` registra nome e argumentos tipados, sem Tcl. Suporta breakpoints preexistentes, timeouts antes/depois de aplicar uma mutação e memória determinística de 64 KiB. Falha em chamada inesperada para evitar testes permissivos que escondem erros de fluxo.

## 5. `session`: estado, execução e inspeção

### 5.1 `session/state.py`

| Tipo | Campos/finalidade |
| --- | --- |
| `SessionState` | disconnected/running/stopped/unknown/closed |
| `SessionConfig` | Assinatura opcional, modo inicial, intervalo de polling, limites de step/frame, timeout de execução opcional |
| `StopSnapshot` | stop_id, memory_epoch, registradores, resolução de PC, status da assinatura, motivo conhecido |
| `SelectionState` | stop_id e índice do frame selecionado; mutável apenas pela sessão |
| `StopCache` | Cache privado de bytes, frames e análise do estado de funções |
| `SignatureSpec` | Endereço e bytes esperados, com validação do intervalo |
| `InspectionContext` | Protocolo de leitura associado a um stop_id e frame fixos |

Separar `SelectionState` do snapshot imutável permite selecionar frame sem alterar a identidade da parada.

```python
class InspectionContext(Protocol):
    @property
    def stop_id(self) -> int: ...
    @property
    def frame(self) -> Frame: ...
    @property
    def registers(self) -> RegisterSet: ...
    @property
    def symbol_context(self) -> SymbolContext: ...
    def read_memory(self, address: int, size: int) -> bytes: ...
    def locate_variable(self, variable: Variable) -> LocationResult: ...
    def validate(self) -> None: ...
```

Contexto não possui métodos de execução. Acesso após invalidação lança `StaleInspectionError`. Criação/verificação confirma alvo parado; a conclusão de inspeções compostas valida novamente. Caches são compartilhados internamente na parada, mas a seleção capturada pelo contexto não muda durante uma avaliação.

### 5.2 `session/results.py`

Resultados de domínio, sem strings de apresentação Rich/JSON:

| Tipo | Conteúdo |
| --- | --- |
| `StopResult` | Snapshot, números de breakpoints coincidentes, motivo do término e avisos |
| `ResolvedTarget` | Endereço e `Resolution[CodeLocation]`, descrição original e eventual avanço de linha |
| `TargetQuery` | União de endereço, símbolo ou arquivo/linha com imagem opcional |
| `LocationResult` | Storage materializado em endereço ou bytes de registradores, ou motivo de indisponibilidade |
| `DisassemblyResult` | Instruções e anotações offline, PC e cursor seguinte |
| `CloseReport` | Remoções confirmadas, ids pendentes, criações de resultado desconhecido, erros |
| `SessionError` | Base para erros de estado, alvo ambíguo/inexistente, segurança e inspeção obsoleta |

`LocationResult` não contém formatação ou decodificação C: isso pertence a `eval`. Anotações de disassembly preservam múltiplos candidatos quando necessário.

### 5.3 `session/core.py`

Fachada usada por handlers. Constrói os serviços internos a partir do projeto, target e políticas injetados.

```python
class Session:
    def __init__(self, project: Project, target: Target,
                 config: SessionConfig, safety: SafetyGate,
                 clock: Clock) -> None: ...
    def attach(self) -> SessionState: ...
    def reconcile(self) -> SessionState: ...
    def resolve_target(self, query: TargetQuery) -> Resolution[ResolvedTarget]: ...
    def execute(self, request: ExecutionRequest,
                cancel: CancellationToken) -> StopResult: ...
    def where(self) -> StopResult: ...
    def inspection(self) -> InspectionContext: ...
    def backtrace(self) -> BacktraceResult: ...
    def select_frame(self, index: int) -> Frame: ...
    def add_breakpoint(self, target: ResolvedTarget) -> BreakpointRecord: ...
    def delete_breakpoint(self, number: int) -> None: ...
    def suspend_breakpoint(self, number: int) -> BreakpointRecord: ...
    def resume_breakpoint(self, number: int) -> BreakpointRecord: ...
    def breakpoints(self) -> tuple[BreakpointRecord, ...]: ...
    def disassemble(self, address: int, count: int) -> DisassemblyResult: ...
    def pages(self) -> tuple[PageState, ...]: ...
    def page3(self, policy: MemoryLayoutPolicy) -> Page3Report: ...
    def set_mode(self, mode: StepMode) -> None: ...
    def save(self) -> None: ...
    def reset(self, permit: ConfirmationPermit) -> None: ...
    def load(self, permit: ConfirmationPermit) -> None: ...
    def close(self) -> CloseReport: ...
```

`attach` consulta estado, sem pausar automaticamente; se parado, captura snapshot. `where` reapresenta a parada existente após conferir estado, sem zerar um frame escolhido pelo usuário. Uma nova parada real cria novo snapshot e frame 0. `reconcile` consulta CPU e breakpoints próprios sem repetir mutações incertas.

`close` tenta limpeza de todos os ids próprios conhecidos mesmo após uma falha individual, fecha transporte e é idempotente. O relatório não mascara a exceção original. Não garante remoção de breakpoint cujo id nunca foi recebido após uma criação com timeout.

### 5.4 `session/execution.py`

```python
class ExecutionRequest:
    kind: ExecutionKind
    address: Optional[int]
    mode: StepMode
    timeout_seconds: Optional[float]

class ExecutionController:
    def run(self, request: ExecutionRequest, hooks: ExecutionHooks,
            cancel: CancellationToken) -> StopResult: ...

class Clock(Protocol):
    def monotonic(self) -> float: ...
    def sleep(self, seconds: float) -> None: ...

class CancellationToken(Protocol):
    def is_cancelled(self) -> bool: ...
```

`ExecutionKind`: continue, step, next, stepi, finish, until. `ExecutionHooks` é um protocolo interno de callbacks da sessão: invalidar estado, capturar parada e consultar breakpoints ativos. O controlador recebe Target/Project/Clock no construtor; não chama a fachada Session recursivamente.

Invalida antes de enviar controle; espera parada para todas as operações, inclusive finish. No step por linha, compara imagem/módulo/arquivo/linha; 20.000 iterações são limite de passos solicitados, não contagem comprovada das instruções executadas por step-over. Timeout usa relógio monotônico e cobre a operação inteira, não reinicia por iteração. Interrupção/timeout solicita break e aguarda confirmação com prazo limitado; se não confirmar, a sessão fica unknown e não retorna snapshot inventado.

### 5.5 `session/breakpoints.py`

```python
class BreakpointManager:
    def create(self, target: ResolvedTarget) -> BreakpointRecord: ...
    def delete(self, number: int) -> None: ...
    def suspend(self, number: int) -> BreakpointRecord: ...
    def resume(self, number: int) -> BreakpointRecord: ...
    def records(self) -> tuple[BreakpointRecord, ...]: ...
    def matching(self, address: int) -> tuple[int, ...]: ...
    def reconcile(self) -> tuple[BreakpointRecord, ...]: ...
    def cleanup(self) -> CloseReport: ...
```

`BreakpointRecord`: número, endereço, localização original, remote_id opcional, status active/suspended/unknown. O número é reservado antes da tentativa de criação e nunca reutilizado. Timeout de criação pode deixar registro unknown sem id; não se toma posse de breakpoint externo apenas por coincidência de endereço. Reconciliação remove essa incerteza somente com evidência suficiente, caso contrário a mantém e a relata.

Exclusão e suspensão alteram bookkeeping somente após confirmação. Retomada sem confirmação não é repetida automaticamente. Breakpoints externos nunca entram na lista de limpeza.

### 5.6 `session/frames.py`

```python
class FrameService:
    def walk(self, snapshot: StopSnapshot, reader: FrameReader) -> BacktraceResult: ...
    def frame_state(self, function: Function, pc: int,
                    reader: FrameReader) -> FrameState: ...
    def locate(self, variable: Variable, frame: Frame,
               registers: RegisterSet, reader: FrameReader) -> LocationResult: ...
```

`Frame`: índice, PC exibido, PC de escopo, função resolvida, IX opcional, estado de frame. `FrameState`: IX ativo, sem frame com SP de entrada demonstrado, ou desconhecido. `BacktraceResult`: frames e razão de término. `FrameReader` fornece memória e disassembly sob controle da sessão, sem operações de execução.

O chamador usa return_address para apresentação e return_address−1 para escopo. Caminhada limita a 64 frames, detecta ciclos e interrompe em dados inválidos. Análise estática de `pop ix` não comprova execução de um caminho. Endereço SP-relativo só é oferecido com evidência da posição de SP; registradores de chamadores são indisponíveis.

Cache de estado é por parada e FunctionId; análise estrutural do código só pode sobreviver a paradas se houver evidência de código inalterado. A primeira versão invalida conservadoramente a cada retomada, evitando assumir ausência de automodificação ou troca de mapper.

### 5.7 `session/safety.py`

```python
class SafetyGate:
    def authorize_typed(self, action: DangerousAction,
                        entry: InteractiveEntry) -> ConfirmationPermit: ...
    def consume(self, permit: ConfirmationPermit,
                action: DangerousAction) -> None: ...

class SignatureGuard:
    def check(self, reader: SignatureReader) -> SignatureStatus: ...
    def rearm(self) -> None: ...
```

`DangerousAction` é reset/load. `InteractiveEntry` contém texto literal e origem fresh-input; entradas de repetição/lote não satisfazem o contrato. `ConfirmationPermit` é opaco, vinculado à sessão e ação, consumido antes do envio e não reutilizável após erro. Apenas o adaptador interativo solicita emissão; testes usam instâncias controladas. Isso é uma restrição de API/fluxo, não prova criptográfica de presença humana.

`SignatureStatus`: not-configured, pending, verified. Guard é rearmado em reset/load/reconexão. Pending permite inspeção bruta e relatório de parada, mas bloqueia interpretação C confiável. O leitor de assinatura usa bytes do Target sem depender de resolução offline.

### 5.8 `session/memory_map.py`

```python
class MemoryMapService:
    def page3(self, context: InspectionContext,
              project: Project, policy: MemoryLayoutPolicy) -> Page3Report: ...
```

`MemoryLayoutPolicy` descreve fontes dos limites: símbolo/endereço e eventual leitura de palavra. `Page3Report` contém regiões conhecidas/desconhecidas, tamanho livre opcional e avisos. Um perfil de compatibilidade pode referir `_g_HeapStartAddress`, sem fixá-lo no serviço. Limites invertidos ou ausentes não geram tamanhos presumidos.

## 6. `eval`: parsing, localização e valores

### 6.1 `eval/tokens.py` e `eval/ast.py`

```python
# tokens.py
def tokenize(text: str) -> tuple[Token, ...]: ...
```

`Token(kind, lexeme, start, end)` preserva posições para erros. `ExpressionSyntaxError` contém intervalo e mensagem. `ast.py` define nós imutáveis `Number`, `Name`, `Unary`, `Binary`, `Group`, `Indirect` e `Index`. `Member`, `Dereference` e `AddressOf` ficam reservados à etapa futura, sem aceitação prematura no parser.

`Group` preserva agrupamento e origem dos parênteses; não significa leitura indireta sem tipo. `BuiltinCall` representa hex/bin após a expansão de macros. AST não acessa sessão, tipo ou memória.

### 6.2 `eval/parser.py`

```python
class ExpressionParser:
    def parse_expression(self, text: str) -> Expr: ...
    def parse_print(self, arguments: ExpandedTokens,
                    explicit_type: Optional[str]) -> PrintRequest: ...
```

`PrintRequest(expression, type_name, mode, source_text)` representa o pedido completo; mode distingue calculate/read-memory/inspect-variable. O dispatcher separa nome de comando, sufixo `/TIPO` e tipo final legado apenas quando inequívoco, preservando os argumentos de macro. Tokenização e expansão acontecem antes de parse_print; classificação definitiva de identificadores usa os índices offline e, somente se necessário, o contexto vivo. `parse_expression` serve `info symbol`, sem aplicar a convenção de print que transforma um registrador isolado em valor exibível.

### 6.3 `eval/values.py`

| Tipo | Contrato |
| --- | --- |
| `ScalarValue` | Valor inteiro/float/bool, tipo e bytes originais |
| `AddressValue` | Endereço, tipo referenciado opcional |
| `LValue` | Tipo e storage materializado, sem leitura implícita |
| `DecodedValue` | União de escalar, string, array e struct; árvore sem markup |
| `ValueResult` | Valor opcional, espécie calculation/memory/variable, display_base 10/16/2, localização, disponibilidade e ressalvas |
| `VariableRow` | Variável, localização e ValueResult |
| `ValueLimits` | Máximo de string 256, elementos exibidos 16 e limite de leitura composta |

```python
class ValueDecoder:
    def decode(self, data: bytes, type: TypeDef,
               types: Project, limits: ValueLimits) -> DecodedValue: ...

def default_print_type(variable: Variable, project: Project) -> Resolution[TypeDef]: ...
```

Decoder é puro; recebe bytes, não reader. Strings registram se terminaram em NUL e se foram truncadas. Floats não finitos exigem representação JSON explícita, sem emitir `NaN`/`Infinity` inválidos: valor numérico nulo com classificação e bytes brutos. Defaults para ponteiros/compostos não são inferidos em print; info locals mantém a política própria documentada.

### 6.4 `eval/evaluator.py`

```python
class Evaluator:
    def __init__(self, project: Project, decoder: ValueDecoder,
                 limits: ValueLimits) -> None: ...
    def evaluate_address(self, expression: Expr,
                         context: InspectionContext) -> int: ...
    def requirements(self, request: PrintRequest) -> EvaluationRequirements: ...
    def evaluate_print(self, request: PrintRequest,
                       context: Optional[InspectionContext] = None) -> ValueResult: ...
    def evaluate_variables(self, variables: Sequence[Variable],
                           context: InspectionContext) -> tuple[VariableRow, ...]: ...
```

Não controla CPU nem retém contexto entre comandos. O cálculo constante funciona sem contexto vivo; requirements identifica necessidade de inspeção após expansão. Preserva a impressão de identificadores isolados conforme COMMANDS, mas aritmética sem tipo calcula valores: símbolo MAP fornece endereço e variável CDB tipada fornece valor. Apenas conversão para endereço aplica máscara de 16 bits; resultados de cálculo não são truncados. Divisão usa truncamento inteiro sem conversão a float. Leitura usa contexto validado e caches da parada. Para structs lê o bloco uma vez e decodifica localmente. Erros públicos: `EvaluationError`, `UnknownName`, `AmbiguousName`, `UnknownType`, `InvalidOperation`; indisponibilidade de variável é resultado, não falha fatal de tabela inteira.

## 7. `ui`: comandos e apresentação

### 7.1 `ui/results.py`

```python
class CommandResult:
    command: str
    ok: bool
    payload: Optional[CommandPayload]
    warnings: tuple[Diagnostic, ...]
    error: Optional[CommandError]

class CommandError:
    code: str
    message: str
    details: Mapping[str, object]
```

`CommandPayload` é união fechada de resultados: parada, resolução offline, breakpoint(s), registradores, páginas/page3, frames, fontes, disassembly, valor(es), modo, ajuda e confirmação de operação. `UiAction` separado representa clear/quit; não é executado pelo renderizador. Invariante: falha tem error e nenhum payload de sucesso. Índice de comando e versão JSON pertencem ao envelope de serialização, não ao domínio.

### 7.2 `ui/registry.py`

```python
class CommandSpec:
    name: str
    aliases: tuple[str, ...]
    help_text: str
    syntax: str
    repeatable: bool
    confirmation: Optional[DangerousAction]
    parser: Callable[[str], CommandArguments]
    handler: Callable[[CommandArguments, CommandContext], CommandResult]
    completer: Callable[[CompletionRequest], tuple[Completion, ...]]

class CommandRegistry:
    def register(self, spec: CommandSpec) -> None: ...
    def lookup(self, name: str) -> CommandSpec: ...
    def specifications(self) -> tuple[CommandSpec, ...]: ...
    def complete(self, request: CompletionRequest) -> tuple[Completion, ...]: ...
```

Registro rejeita nomes/aliases duplicados. `CommandArguments` são dataclasses por família, sem dicionários posicionais soltos. `CompletionRequest` tem texto/cursor e catálogo offline; completion não envia comandos ao emulador. Requisitos de estado são verificados pelos casos de uso, mesmo se a UI também os indicar na ajuda.

### 7.3 `ui/commands.py`

```python
def build_registry() -> CommandRegistry: ...
def parse_target(text: str) -> TargetQuery: ...

class CommandDispatcher:
    def dispatch(self, text: str, context: CommandContext) -> CommandResult: ...
```

`CommandContext`: Session, Project, SourceRepository, MacroCatalog, contexto offline de macros, Evaluator, NavigationState e origem da entrada; não contém Target. `NavigationState` guarda `SourceCursor` e `DisassemblyCursor`. `parse_target` interpreta qualificador de imagem antes de arquivo:linha; não usa parser aritmético para ampliar acidentalmente a sintaxe de break.

| Handlers a definir | Colaboração principal |
| --- | --- |
| `handle_break`, `handle_delete`, `handle_suspend`, `handle_resume` | Resolução tipada e métodos de breakpoint da Session |
| `handle_continue`, `handle_step`, `handle_next`, `handle_stepi`, `handle_finish`, `handle_until` | ExecutionRequest e Session.execute |
| `handle_where`, `handle_backtrace`, `handle_frame` | Parada e frames da Session |
| `handle_list` | Project, SourceRepository e SourceCursor |
| `handle_disassemble` | Resolver endereço, Session.disassemble e DisassemblyCursor |
| `handle_print` | Tokenizer, MacroExpander, ExpressionParser, Evaluator e InspectionContext somente quando necessário |
| `handle_info` | Subdispatch explícito para os sete subcomandos documentados |
| `handle_mode`, `handle_save`, `handle_reset`, `handle_load` | Session e autorização especial quando aplicável |
| `handle_clear`, `handle_help`, `handle_quit` | Ação UI ou metadados do registro |

Todos seguem a assinatura handler de CommandSpec. `handle_info` avalia locals/args via Evaluator, sem introduzir dependência session→eval. `info symbol` usa evaluate_address seguido de nearest_symbol. Resultados de parada são enriquecidos com fonte/disassembly antes de chegar ao renderizador; assinatura pending usa somente dados brutos.

### 7.4 `ui/repl.py` e `ui/batch.py`

```python
class Repl:
    def run(self, context: CommandContext) -> int: ...

class BatchRunner:
    def run(self, commands: Sequence[str], context: CommandContext,
            writer: TextIO) -> int: ...
```

Repl possui PromptSession, histórico e comando repetível. Entrada vazia repete somente comando permitido; reset/load exigem literal novo e permit de uso único. Ctrl-C é convertido em cancelamento durante execução e tratado no prompt. EOF/quit terminam o loop.

Batch envia comandos sequencialmente, com origem batch, interrompe no primeiro erro e exige prazo finito de execução. Reset/load são recusados antes da emissão e também protegidos pela sessão. Política de clear em batch continua pendente, como em COMMANDS; não deve ser implicitamente convertido em efeito de terminal no JSON.

O escopo de composição usa `try/finally` para Session.close tanto no REPL quanto no lote; runners não duplicam a responsabilidade de destruir a sessão. Relatório de limpeza vai para stderr e pode tornar o código de saída não zero.

### 7.5 Renderizadores

```python
# ui/render_text.py
class TextRenderer:
    def render(self, result: CommandResult, console: Console) -> None: ...

# ui/render_json.py
class JsonRenderer:
    def encode(self, result: CommandResult, command_index: int) -> str: ...
```

TextRenderer escapa strings de símbolos/fontes e aplica estilos. JsonRenderer faz mapeamento explícito versionado, sem serializar indiscriminadamente `__dict__` ou dataclasses internas. `encode` retorna um objeto JSON sem newline; BatchRunner acrescenta exatamente uma quebra. Endereços são inteiros, enums têm valores estáveis e bytes usam representação hexadecimal documentada por campo.

## 8. Entrada e composição: `__main__.py`

```python
def main(argv: Optional[Sequence[str]] = None) -> int: ...
def build_argument_parser() -> ArgumentParser: ...
def run_resolve(options: ResolveOptions) -> int: ...
def run_shell(options: ShellOptions) -> int: ...
def run_exec(options: ExecOptions) -> int: ...
```

O incremento offline implementa `main`, `build_argument_parser` e `run_resolve` somente para `resolve` e `--version`. Alvos: hexadecimal `0xADDR` e `arquivo:linha`, opcionalmente `image::`. Ids CLI são nomes dos diretórios de saída quando únicos, ou paths absolutos quando os nomes colidem. `--map` com múltiplos `--out` é recusado antes da carga. `run_shell`, `run_exec` e o manifesto permanecem pendentes. O texto de fonte vem do listing quando disponível; leitura de arquivos de fonte pertence ao próximo incremento de `SourceRepository`.

`ResolveOptions`, `ShellOptions`, `ExecOptions` são configurações normalizadas do CLI. `resolve` constrói loader/projeto/fontes e renderiza sem instanciar transporte ou sessão. Restringe alvos à sintaxe offline documentada, mesmo que Project ofereça consultas mais amplas.

Shell/exec compõem transporte, target, SafetyGate, Session, avaliador, registro e UI. Mantêm o fechamento em finally e retornam códigos de saída documentados. `--version` não carrega projeto nem acessa socket. Não executar trabalho em import de módulo.

## 9. Fluxos de colaboração

### Resolução offline

```text
CLI.run_resolve
  → ProjectLoader.load(ProjectSpec)
  → parsers → reconciliação → Project
  → Project.resolve / resolve_line
  → CommandResult → TextRenderer
```

Resultado ambíguo/não encontrado não abre sessão para tentar adivinhar a imagem ativa.

### Criação de breakpoint

```text
Dispatcher → parse_target → Session.resolve_target
  → Project.lookup_symbol / resolve_line (ou endereço direto)
  → Session.add_breakpoint → BreakpointManager.create
  → Target.create_breakpoint → OpenMSXTransport.request
  → confirmação → registro local → CommandResult
```

Um endereço numérico continua válido com localização offline ausente/ambígua. Um alvo simbólico com vários endereços exige desambiguação antes da mutação. Timeout após envio deixa estado unknown, sem retry automático.

### Step e parada

```text
Dispatcher → ExecutionRequest → Session.execute
  → invalidar snapshot → ExecutionController.run
  → Target.step_into/over → polling de execution_status
  → leitura de registradores e assinatura → Project.resolve
  → comparar linha e limites; repetir se necessário
  → novo StopSnapshot, seleção frame 0 → StopResult
  → enriquecer fonte/disassembly → renderizar
```

Paradas intermediárias do step podem usar caches transitórios; não podem reaproveitar memória da iteração anterior.

### Print e variáveis

```text
Dispatcher → separar tipo explícito → tokenize → MacroExpander.expand
  → ExpressionParser.parse_print → Evaluator.requirements
  → Session.inspection somente se necessário → contexto da parada/frame
  → Evaluator.evaluate_print
  → Project.find_variable / lookup_symbol / lookup_type
  → context.locate_variable → FrameService (se necessário)
  → context.read_memory → cache/Target
  → cálculo puro ou ValueDecoder → ValueResult → validar contexto se utilizado
  → CommandResult → TextRenderer ou JsonRenderer
```

Não há caminho Evaluator→Session.execute nem renderizador→Target.

## 10. Contratos de erro e testes

O [TEST_PLAN.md](TEST_PLAN.md) detalha a matriz por módulo, função pública e handler, incluindo stubs, fixtures, falhas, F17/F18 e critérios de conclusão. Alterações nos contratos públicos devem atualizar essa matriz.

| Fronteira | Comportamento de erro | Testes essenciais |
| --- | --- | --- |
| Parser | Diagnósticos por item com origem | Fixtures reais, registros truncados, identidades repetidas |
| Loader/Project | Falha de carga ou Resolution explícita | Bases conflitantes, dois statics homônimos, caminhos por componentes |
| Transporte | Exceção tipada, sem mutação repetida | XML fragmentado, escaping, eventos intercalados, timeout após envio |
| Target | DTOs completos ou erro | Mesma suíte de contrato para FakeTarget e adaptador controlado |
| Session | Snapshot válido ou estado unknown | Invalidação, finish aguardando, Ctrl-C, timeout total, contexto obsoleto |
| Breakpoints | Preserva incerteza e propriedade | Falhas em create/delete/resume, id desconhecido, preservação de externos |
| Frames | Indisponibilidade explicada | Ciclos IX, múltiplos epílogos, ausência de frame, caller sem registradores |
| Safety | Recusa antes da operação | Lote, repetição, permit reutilizado/trocado entre ações, assinatura rearmada |
| Eval | Sintaxe precisa ou valor indisponível | Espaços, agrupamento, divisão negativa, hex/bin, expansão/ciclos, cálculo sem Target e leituras limitadas |
| UI/JSON | Envelope coerente e saída estável | Aliases completos, goldens, stdout JSON puro, limpeza com erro |

Não acoplar testes de Session às strings Tcl; usar FakeTarget. Testes de parser devem usar fixtures reais SDCC quando disponíveis. Integração live é opt-in e conecta somente a emulador preparado pelo operador. Os testes históricos citados na SPEC ainda não estão neste diretório.

## 11. Ordem de estabilização e decisões pendentes

1. Estabilizar identidade, Resolution, origens, ProjectSpec e consultas offline.
2. Estabilizar Target, seus DTOs/erros e FakeTarget.
3. Implementar estado de sessão, breakpoints e caminho comum de execução.
4. Estabilizar InspectionContext, frames e localização de variáveis.
5. Implementar catálogo/expansão de macros, AST, calculadora hex/bin, decodificação e avaliador com contexto vivo opcional, sem dependência da UI.
6. Integrar registro, handlers e renderizadores sobre os contratos anteriores.

Permanecem pendentes de evidência: protocolo persistente, leitura em bloco, tipos CDB T, ABI de float e provas de frame. Permanecem pendentes de definição de interface externa: esquema final do manifesto, parâmetro/default de timeout de exec, política de clear em lote e configuração dedicada de fontes/include paths/flags para macros. Os contratos internos acima permitem avançar sem apresentar essas decisões como concluídas.

Este documento deve ser atualizado quando um contrato público mudar, junto com os testes afetados. Novos métodos privados não exigem revisão do desenho; novas dependências entre camadas ou mudanças de semântica exigem.

## 12. Extensões rastreadas no backlog

O [BACKLOG.md](BACKLOG.md) define os requisitos F01–F18 e seu impacto nos módulos. Os contratos deste documento continuam sendo os do núcleo proposto; os itens adiados não são APIs disponíveis.

- F08/F09 exigem predicados tipados e qualificadores em breakpoints, traduzidos por OpenMSXTarget.
- F10 exige operações próprias de watchpoints, registro de propriedade e limpeza em Session.close.
- F13 exige associação explícita entre imagens e mapeamentos observados no snapshot.
- F14/F15 exigem operações de escrita tipadas em Target/Session/FakeTarget, alvo parado, invalidação antes da mutação e leitura de verificação; sem retry automático em resultado incerto.
- F07 estende ExecutionRequest com política limitada de espera por assinatura, sem reset/load automático.
- F11/F16 estendem evidências de áreas e localização, sem inferir endereço estático a partir de offset isolado.

A sintaxe e as assinaturas dessas extensões devem ser detalhadas ao promover cada item para implementação. Nenhuma delas introduz inicialização do emulador, gerenciamento de mídia ou bypass de confirmação humana.


## 13. Contratos adicionais: calculadora e macros (F17/F18)

Esta seção refina §§6–7: o pipeline passa a ser tokens → expansão de macros → AST → avaliação de valor ou leitura explícita. Não há código implementado. A seleção de modo segue COMMANDS §8; ela substitui a convenção anterior de parênteses externos sem tipo como indirection.

### `debuginfo/macros.py`: definições offline

`MacroDefinition` contém nome, parâmetros opcionais (None para macro de objeto, tupla vazia para macro sem argumentos), tokens de substituição, Origin e contexto de imagem/unidade de compilação. `MacroContext` identifica contexto de compilação conhecido; `MacroToken` é dado lexical offline, sem dependência de eval. `MacroCatalog` é imutável e não colapsa definições conflitantes.

```python
class MacroCatalog:
    def lookup(self, name: str,
               context: MacroContext) -> Resolution[MacroDefinition]: ...
    def names(self, context: MacroContext) -> tuple[str, ...]: ...

def parse_macro_definitions(text: str, origin: Path,
                            context: MacroContext) -> ParseResult[tuple[MacroDefinition, ...]]: ...
```

Loader compõe catálogo a partir das entradas explicitamente carregadas, incluindo headers. Extração de defines preserva tokens, em vez de somente o valor inteiro hoje usado para tamanhos de array. Contexto condicional não demonstrado torna a definição indisponível/ambígua. O parser de structs pode continuar com seu subconjunto de constantes sem importar eval.

### `eval/macros.py`: expansão limitada

```python
class MacroExpander:
    def expand(self, tokens: Sequence[Token], catalog: MacroCatalog,
               context: MacroContext, limits: ExpansionLimits) -> ExpandedTokens: ...
```

`ExpandedTokens` inclui tokens e mapa de origens/cadeia de expansão. `ExpansionLimits` limita profundidade e total de tokens. O expander converte MacroToken em Token localmente, substitui parâmetros por tokens, reconhece argumentos aninhados e preserva precedência textual. Detecta ciclo/aridade/construção não suportada antes da avaliação. Nomes reservados hex/bin não são sobrescritos. Não usa eval do Python nem executa pré-processador externo.

### AST, avaliação e resultados

O contrato consolidado de §6 inclui `BuiltinCall(name, arguments)` à AST para hex/bin; chamadas de macros desaparecem na expansão, outras chamadas são rejeitadas. `PrintRequest` tem `mode` explícito (calculate, read-memory, inspect-variable), determinado após expansão. A UI separa o tipo externo, mas não tenta dividir argumentos de macro por espaços.

```python
class EvaluationRequirements:
    needs_live_context: bool
    needs_types: bool

class Evaluator:
    def requirements(self, request: PrintRequest) -> EvaluationRequirements: ...
    def evaluate_print(self, request: PrintRequest,
                       context: Optional[InspectionContext] = None) -> ValueResult: ...
```

Essas assinaturas repetem os pontos relevantes da fachada consolidada de §6.4; não definem uma segunda classe de implementação. O projeto e o catálogo são dependências offline. Contexto ausente só é permitido quando a expressão não necessita dados vivos; nomes ambíguos/ausentes falham explicitamente. Dispatcher solicita Session.inspection apenas quando necessário. `evaluate_address` permanece separado e mantém sua conversão final para endereço; cálculo não mascara o resultado.

`ValueResult` tem espécie calculation/memory/variable e `display_base` (10/16/2). Hex/bin retornam inteiro preservado com indicação de formato na chamada externa, nunca string intermediária. JsonRenderer emite valor numérico e base; TextRenderer aplica prefixo e sinal. Memória e variáveis mantêm localização e proveniência. Completion inclui macros no contexto conhecido sem I/O vivo.

Testes adicionais: precedência após expansão textual; macros encadeadas, parâmetros repetidos e argumentos aninhados; colisão por imagem, conditional desconhecido e ciclos; resultado maior que 16 bits; hex/bin negativos/aninhados; ausência de chamada Target em cálculo constante; compatibilidade de print tipado e migração explícita de parênteses.
