# Validação da fase 8

## Resultado

F05/F06 estão implementados e validados offline. A suíte completa registra:

```text
393 passed, 5 skipped, 14 subtests passed
```

## Evidência de tipos e ABI

- `tests/fixtures/cdb/msxciv_sdcc_4_6_types.cdb` contém registros `T:` mínimos
  extraídos do `out/msxciv.cdb` real, incluindo arrays com sufixo decimal,
  structs aninhadas, ponteiro de função preservado e bitfield rejeitado.
- `tests/fixtures/cdb/phase8_types.c` foi compilado pelo SDCC 4.6.0 #16555
  para Z80. O `.adb` resultante é mantido como fixture.
- Os inicializadores `0.0f`, `1.0f` e `-2.5f` produziram respectivamente
  `00 00 00 00`, `00 00 80 3f` e `00 00 20 c0`, comprovando binary32
  little-endian para essa combinação de compilador/target.
- Uma carga completa do diretório `msxciv/out` produziu 1.536 tipos: 980
  structs, 275 arrays, 224 inteiros, 29 ponteiros, 26 incompletos e 2 void.

## Expressões e localização

Há cobertura para `*p`, `&x`, `a[i]`, `s.f` e `p->f`, precedência postfix,
aritmética com campos, escala por tamanho, offset comprovado e expansão de macro
antes do parser. A localização foi testada em frame atual, caller com IX, global,
static e registradores. Caller não recebe armazenamento em registradores do frame
vivo e `&` rejeita lvalue sem endereço de memória.

## Degradação explícita

Bitfields, unions, casts C e execução de funções permanecem fora do escopo.
Tipos incompletos, campos desconhecidos, operadores incompatíveis, limites de
array violados e endereços fora do espaço Z80 falham sem presumir layout ou ler
memória acidentalmente.

## Validação live

Com o openMSX pausado pela operação allowlisted `debug break`, duas leituras não
destrutivas foram executadas contra o `out` real do msxciv:

- `print &g_MouseState` retornou o endereço `0xC341` e referência ao tipo
  `T:Mouse_State`, sem leitura acidental do objeto;
- `print g_MouseState.Buttons` retornou o escalar `3`, byte bruto `03`, na
  localização `0xC341`.

Nenhum reset, load ou escrita de memória/registrador foi executado. O openMSX
permaneceu pausado após o teste.
