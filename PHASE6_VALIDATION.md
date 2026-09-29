# msxdbg — Consolidação e evidências da fase 6

Data da validação: **2026-09-29**. Ambiente live: **openMSX 21.0**, conectado
por socket Unix a uma instância previamente iniciada e preparada pelo operador.
O msxdbg não iniciou o emulador, não inseriu mídia, não executou reset/load e
não alterou sua velocidade.

## Resultado consolidado

A fase 6 está funcionalmente concluída:

| Entrega | Evidência |
| --- | --- |
| Descoberta de socket | Path explícito e descoberta determinística; somente socket Unix; ausência gera erro attach-only |
| Transporte per-command | XML incremental, fragmentação byte a byte, escaping, eventos, ok/nok, timeout, EOF e fechamento testados |
| `OpenMSXTarget` | Registradores, memória, disassembly, páginas, execução, breakpoints e save/load cobertos por transporte scripted |
| Integração read-only | Attach, status, registradores, memória, disassembly, páginas e listagem aprovados live |
| Exec JSON | `where` e `info registers` aprovados live com os artefatos reais do msxciv |
| Breakpoint | Criação, listagem pelo id remoto e remoção no `finally` aprovadas live |
| Execução | Um `step_in` e confirmação posterior de parada aprovados live |
| Conexão persistente | Múltiplas requisições em uma conexão aprovadas live; conexão defeituosa é descartada sem retry de mutação |
| Leitura em bloco | `debug read_block` comparado ao fallback; 64 KiB e bytes `00`/`FF` aprovados live |

## Execuções registradas

Os comandos opt-in foram executados separadamente para não ampliar autorização
por consequência:

| Cenário | Resultado observado |
| --- | --- |
| Read-only | 1 passou, 3 ignorados intencionalmente |
| Read-only + exec JSON | 2 passaram, 2 ignorados intencionalmente; 17,51 s |
| Breakpoints | 2 passaram, 2 ignorados intencionalmente; 0,70 s |
| Um `step_in` | 2 passaram, 2 ignorados intencionalmente; 1,10 s |
| Persistência + bloco | 2 passaram, 3 ignorados intencionalmente; 1,00 s |

Na consolidação final sem variáveis live, a suíte local apresentou **371 testes
aprovados, 5 live ignorados e 15 subtests aprovados**. Skips live representam
ausência deliberada de opt-in, nunca aprovação presumida.

## Descobertas durante a validação

- O MAP real do SDLD 05.50 usa o cabeçalho estendido `Value Global Global
  Defined In Module` e separadores com múltiplos blocos. O parser foi corrigido
  e ganhou teste de regressão.
- A carga real do msxciv encontrou 18.660 símbolos e 57 módulos. O diretório
  também produz 26.036 avisos LST não fatais e leva aproximadamente 17–20 s
  para carregar; por isso o supervisor do subprocesso live permite 120 s.
- A primeira projeção Tcl da lista de breakpoints preservava uma barra antes da
  quebra de linha. A serialização foi corrigida e revalidada live.

## Seleção e fallback das otimizações

O CLI não assume suporte com base apenas na versão. No attach ele executa
sondagens read-only: duas expressões na mesma conexão comprovam persistência e
uma leitura binária de um byte comprova `read_block`. Somente após as três
respostas válidas habilita `TargetCapabilities(persistent=True,
block_read=True)`. Qualquer falha fecha a conexão de prova e cria transporte
per-command com leitura agregada em Tcl.

Timeout ou perda de conexão depois do envio de uma mutação conserva
`outcome_unknown=True`; a operação nunca é reenviada automaticamente.

## Reprodução

As variáveis e comandos estão documentados em
`tests/integration/README.md`. Os testes mutáveis exigem opt-ins separados:
`MSXDBG_LIVE_BREAKPOINTS=1` e `MSXDBG_LIVE_EXECUTION=1`. A validação das
otimizações exige `MSXDBG_LIVE_OPTIMIZATIONS=1` e transfere os 64 KiB do espaço
de endereçamento, mas não altera o estado emulado.

## Fora do escopo desta conclusão

A fase 6 não promove funcionalidades adiadas como watchpoints, condições de
breakpoint, escrita de memória/registradores ou continuação até assinatura.
Também não conclui ABI de float, todas as construções CDB T, manifesto externo
multi-imagem ou configuração completa de contexto de macros.
