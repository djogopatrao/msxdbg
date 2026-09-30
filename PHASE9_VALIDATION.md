# Validação da fase 9 — em andamento

## F07 — continue --until-signature

Implementado com:

- exigência de assinatura configurada;
- retorno sem retomar quando a parada atual já está verificada;
- timeout positivo e global para toda a operação;
- limite configurável e positivo de paradas (padrão 256);
- cancelamento sem retomada adicional;
- erro de limite somente após preservar uma parada confirmada;
- ausência de reset, load ou retry de mutação incerta.

A suíte após o incremento registra:

```text
399 passed, 5 skipped, 14 subtests passed
```

## Sondagem T06

O backend conectado reportou openMSX 21.0. A ajuda read-only confirmou suporte
a `debug breakpoint`, `debug watchpoint` e `debug condition`, todos com operações
create/configure/list/remove. Breakpoints aceitam address, condition, command,
enabled e once. Watchpoints aceitam tipos separados `read_mem`/`write_mem` (e I/O),
endereço simples ou par início/fim, além das mesmas propriedades de condição.

A condição remota é Tcl; por segurança, a fase deve gerar esse texto somente a
partir de uma AST própria e nunca aceitar Tcl do usuário. O backend não oferece
um tipo único `access`, portanto esse modo deverá ser representado por dois
watchpoints remotos com uma única identidade local, ou ser excluído da primeira
entrega mediante decisão explícita.

## F08/F10 — implementados

A sintaxe aprovada foi implementada para `break ALVO if EXPRESSÃO` e `watch
read|write|access ENDEREÇO TAMANHO`. Condições usam lexer/parser próprio e nomes
resolvidos pelo modelo; delimitadores Tcl, substituição de variável/comando e
nomes ambíguos são recusados antes de qualquer criação remota. Globais/statics
inteiros de 8/16 bits são traduzidos com leitura de memória e sinal comprovados.

Breakpoints e watchpoints compartilham números locais. Um watchpoint `access`
mantém dois IDs remotos e suspend/resume/delete/cleanup percorrem todos, mesmo se
uma remoção intermediária falhar. Pontos externos não entram no catálogo próprio.

Validação live no openMSX 21.0 criou/listou/removeu `bp#1` condicional em PC e
`wp#1`/`wp#2` read/write em `0xC341`. A suíte offline registra:

```text
403 passed, 5 skipped, 14 subtests passed
```

## F09 — breakpoint qualificado

A sintaxe `break ALVO [if EXPRESSÃO] [page N] [slot P[.S]] [segment N]` foi
implementada. Página e slots têm domínio 0–3; segmento é não negativo e exige
página explícita. Quando somente slot é fornecido, a página deriva do endereço.
Qualificadores são armazenados no registro local, exibidos em texto/JSON e
traduzidos para consultas allowlisted executadas pelo openMSX no disparo.

A criação verifica capacidades read-only e recusa segmento quando o mapper da
página não é observável. No teste live, PC `0x79D5` estava na página 1, slot
`3.2`; o breakpoint `bp#2` com essa condição foi criado, listado e removido. O
segmento observado era `unknown` e foi corretamente omitido.

Após F09, a suíte completa registra:

```text
409 passed, 5 skipped, 14 subtests passed
```
