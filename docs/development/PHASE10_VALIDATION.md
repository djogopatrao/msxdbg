# Validação da fase 10

## Resultado

A fase 10 foi implementada e validada offline em 2026-09-30.

- `_HOME`, `_GSINIT` e `_GSFINAL` usam bases independentes comprovadas por
  export do listing e endereço ligado no MAP.
- Labels locais, inclusive statics sem CDB, só entram no índice quando a base
  da área é demonstrável; leitura exige tipo explícito.
- O manifesto v1 aceita `mappings` por imagem com `page`, `slot` e `segment`.
  O snapshot registra as páginas observadas e restringe a imagem apenas quando
  uma associação é única.
- `write memory` valida faixa, largura e endianness, invalida o estado antes da
  emissão, relê os bytes e reporta divergência.
- `write register` valida largura, preserva a outra metade de pares e publica
  uma nova geração após releitura.
- Falha com `outcome_unknown` não é repetida e deixa a sessão em estado
  `unknown`. Não há promessa de rollback.

## Evidência automatizada

`python3 -m pytest -q`:

```text
422 passed, 5 skipped, 14 subtests passed
```

`python3 VALIDATE_STUBS.py`:

```text
sintaxe 50 OK/0 falhas; imports 49 OK/0 falhas; arquivos obrigatórios ausentes 0
```

Os testes live continuam opt-in. Nenhum emulador foi iniciado e nenhuma mídia,
velocidade, memória ou registrador de uma sessão real foi alterado durante esta
validação.
