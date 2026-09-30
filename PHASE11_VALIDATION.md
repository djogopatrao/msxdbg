# Validação da fase 11

## Resultado

A fase 11 foi implementada e validada offline em 2026-09-30.

- `pyproject.toml` produz wheel instalável e o entry point `msxdbg`.
- Python 3.10–3.14 compõe a matriz de CI; o pacote declara 3.10 como mínimo.
- Testes live possuem marcador formal e ficam fora da execução offline do CI.
- Instalação, segurança, troubleshooting, compatibilidade, schema JSON,
  changelog e checklist de release estão documentados.
- O benchmark fornece carga de projeto e, com opt-in, attach, leitura de memória
  e step completo até nova parada.
- Diagnósticos repetidos são agregados por código/severidade/mensagem, mantendo
  todas as origens distintas na saída.

## Evidência automatizada

`python3 -m pytest -q`:

```text
419 passed, 5 skipped, 14 subtests passed
```

`python3 -m pytest -q -m 'not live'`:

```text
419 passed, 5 deselected, 14 subtests passed
```

`python3 VALIDATE_STUBS.py`:

```text
sintaxe 50 OK/0 falhas; imports 49 OK/0 falhas; arquivos obrigatórios ausentes 0
```

Uma instalação temporária sem dependências de runtime construiu
`msxdbg-0.11.0rc1-py3-none-any.whl`; o comando instalado respondeu
`msxdbg 0.11.0rc1` e exibiu a ajuda da CLI.

O smoke benchmark de 20 iterações sobre fixtures registrou a carga corretamente.
Números de uma máquina isolada não são promovidos a promessa universal. O
baseline de release em projeto real, assim como openMSX live, permanece opt-in
e deve ser anexado ao release candidate conforme `RELEASE.md`.

## Qualificação live do release candidate

Em 2026-09-30, a suíte live completa passou contra openMSX 21.0 opt e os
artefatos reais de `MSXgl-1.5.0/projects/msxciv/out`:

```text
5 passed in 24.67s
```

Foram validados contrato somente leitura, execução JSON, criação e remoção de
breakpoint próprio, um step com retorno à parada e transporte persistente com
leitura binária. O baseline real está em
`benchmarks/baseline-msxciv-openmsx21.json`. A carga completa do projeto levou
19,159 s nesta máquina; attach 607 ms, leitura de 256 bytes 0,508 ms e step até
nova parada 3,682 ms. Por ser a primeira amostra e ter uma iteração, esses
números são referência inicial, não limite estatístico.
