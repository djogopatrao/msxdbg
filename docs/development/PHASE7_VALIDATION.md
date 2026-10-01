# Validação da fase 7

A fase 7 fecha os serviços concretos que permaneciam como stubs após a fase 6.

## Entregas validadas

- `SourceRepository`: prioridades explícitas, ambiguidade, fallback do listing,
  janelas limitadas, cache por metadados e invalidação seletiva/total.
- `SafetyGate`: confirmação literal e fresca, permit vinculado à sessão e ação,
  consumo único antes da mutação e recusa em batch pela UI.
- `SignatureGuard`: estados não configurada/pendente/verificada, cache após
  verificação, rearme em reset/load e bloqueio da interpretação de variáveis C.
- `MemoryMapService.page3`: política injetável, limites desconhecidos e
  inválidos, SP vivo, aviso de colisão heap/stack e renderização texto/JSON.
- Headers/macros: structs packed do subconjunto documentado, arrays, dependência
  entre tipos, falha isolada, origem, macros e integração no loader. CDB preserva
  precedência sobre o fallback de header.
- Manifesto `--project`: JSON v1, paths relativos, associação por imagem,
  validação antes da conexão e exclusão mútua com opções de artefatos avulsas.

## Verificação

Em 29 de setembro de 2026, `pytest -q` concluiu com 379 testes aprovados e 5
testes live opt-in ignorados. Os testes da fase 7 estão em
`tests/test_phase7_core.py`; os antigos testes que exigiam stubs foram
substituídos por comportamento funcional.

Reset/load continuam ausentes do modo batch. A suíte não inicia openMSX, não
prepara mídia e não automatiza confirmações humanas.

## Validação live

Com o openMSX já preparado e pausado pelo operador, os cinco cenários opt-in
foram aprovados em 29 de setembro de 2026: contrato read-only, execução JSON
read-only com os artefatos reais do msxciv, criação/remoção de breakpoint,
exatamente um `step_in` e comparação da conexão persistente/leitura em bloco de
64 KiB. Nenhum cenário iniciou o emulador, alterou mídia, executou reset/load ou
mudou a velocidade.
