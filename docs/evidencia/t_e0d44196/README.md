# Evidencia C2 — re-despacho automatico de bloqueio transient (t_e0d44196)

Ferramentas de prova versionadas junto do codigo (regra 12-E).

- `baseline.py <kanban.db>`: somente leitura. Mede, na janela de 7 dias,
  bloqueios `kind=transient`, quantos foram retomados, latencia ate o proximo
  `unblocked`/`claimed`, e eventos `unblocked` com `auto=transient_redispatch`.
- `mutantes.sh <worktree>`: 7 sabotagens no codigo; cada uma tem de reprovar
  `tests/hermes_cli/test_kanban_transient_redispatch.py`.
- `prova_viva.py <worktree>`: roda `dispatch_once` real sobre COPIA
  (`sqlite3 backup`) do board atlas, em HERMES_HOME temporario. Nao toca o
  board real nem spawna worker.

## Medido em 2026-11-14 (antes do merge)

Baseline do board atlas, 7 dias:

    {"janela_dias": 7, "blocos_transient": 43, "por_tipo": {"blocked": 27, "block_loop_detected": 16},
     "retomados": 42, "ainda_parados": 1, "latencia_min_mediana": 18.7, "latencia_min_p90": 104.8,
     "auto_redespacho_eventos": 0}

Mutantes (head do PR):

    morto sem_wiring / sem_atraso / qualquer_kind / zera_recorrencia /
    ignora_off / destrava_breaker / ignora_failure_limit   (7/7)

Prova viva na copia do board:

    transient_redispatched: ['t_6eaca764']
    t_6eaca764 ready unblocked {"auto": "transient_redispatch", "delay_seconds": 600, "waited_seconds": 700, ...}
    t_53a090af blocked blocked {"kind": "needs_input", ...}      (controle negativo)
    handoff_no_contexto: True
    cards_reais_retomados_na_copia: []

Os 5 cards hoje em `blocked` no board atlas sao `needs_input` ou sem tipo:
ativar nao move nenhum card existente.

## Aceite do card (latencia de retomada < 15 min) — NAO MEDIDO

Depende de merge, reinicio do gateway com o codigo novo e uma semana de
board. Medir com `python3 baseline.py ~/.hermes/kanban/boards/atlas/kanban.db`:
`auto_redespacho_eventos > 0` e latencia dos retomados automaticos ~10 min.
