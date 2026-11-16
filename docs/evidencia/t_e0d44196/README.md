# Evidencia C2 — re-despacho automatico de bloqueio transient (t_e0d44196)

Ferramentas de prova versionadas junto do codigo (regra 12-E). Rodar com o
python do venv do Hermes (`~/.hermes/hermes-agent/venv/bin/python`); o
`python3` do host nao tem `yaml` e falha nos scripts que importam o Hermes.
`baseline.py` so usa stdlib e roda em qualquer python.

- `baseline.py [kanban.db] [dias]`: somente leitura (`mode=ro`). Na janela
  (padrao 7 dias) mede bloqueios `kind=transient`, quantos foram retomados e a
  latencia ate o proximo `unblocked`/`claimed`/`promoted`. Separa retomada
  automatica (proximo evento e `unblocked` com `payload.auto='transient_redispatch'`)
  de retomada por mao. `auto_redespacho_eventos` conta
  `task_events WHERE kind='unblocked' AND json_extract(payload,'$.auto')='transient_redispatch'`,
  o evento que `hermes_cli/kanban_db_transient.py` grava.
- `controle_baseline.py <worktree>`: prova o instrumento em banco descartavel
  (HERMES_HOME temporario). Positivo: card re-despachado pelo C2 de producao faz
  `auto_redespacho_eventos` subir para 1. Negativo: `unblock_task` manual conta
  como mao, nao como auto. Confere tambem que `baseline.AUTO_MARKER` e igual ao
  de producao. rc=1 se falhar.
- `mutantes_baseline.py <worktree>`: 4 sabotagens no baseline; cada uma tem de
  reprovar `controle_baseline.py`. Inclui o defeito da 1a entrega
  (`kind='transient_retry'`, evento que nenhum codigo emite).
- `mutantes.sh <worktree>`: 11 sabotagens no codigo do C2 (M8-M11 cobrem o
  guarda de transient puro); cada uma tem de reprovar `tests/hermes_cli/test_kanban_transient_redispatch.py`.
- `prova_viva.py <worktree>`: roda `dispatch_once` real sobre COPIA
  (`sqlite3 backup`) do board atlas, em HERMES_HOME temporario. Nao toca o
  board real nem spawna worker.

## Medido em 2026-11-14 (antes do merge)

Baseline do board atlas, 7 dias (instrumento corrigido):

    {"janela_dias": 7, "blocos_transient": 43, "por_tipo": {"blocked": 27, "block_loop_detected": 16},
     "retomados": 42, "retomados_auto": 0, "retomados_mao": 42, "ainda_parados": 1,
     "latencia_min_mediana": 18.7, "latencia_min_p90": 104.8,
     "latencia_auto_min_mediana": null, "latencia_mao_min_mediana": 18.7,
     "auto_redespacho_eventos": 0}

Controle do instrumento (`controle_baseline.py`): PASSA, rc=0;
`auto_redespacho_eventos` 0 -> 0 (unblock manual) -> 1 (C2), latencia auto 11.7 min.

Mutantes do instrumento (`mutantes_baseline.py`):

    morto defeito_velho_transient_retry / conta_todo_unblocked /
    classifica_tudo_mao / marcador_errado   (4/4)

Mutantes do C2 (head do PR):

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

## Guarda de transient puro (t_e146cad1, achado do guardiao t_3066a937)

Defeito: `promote_task` grava `promoted_manual`, nao `unblocked`. Depois de
promote manual de um card bloqueado por transient, o `blocked` antigo seguia
como ultimo evento do filtro `blocked/unblocked/block_loop_detected`. Um trip
sticky posterior do disjuntor (`force_trip`, ex. provider terminal) deixava o
card `blocked` com `block_kind='transient'` herdado e a varredura o devolvia a
fila, anulando o trip. Conserto em `kanban_db_transient._is_pure_transient_block`:
qualquer evento posterior ao `blocked` fora de `_INFORMATIONAL_EVENT_KINDS`
desqualifica (fail-closed), e trip sticky sem `unblocked` humano tambem.

Medido em 2026-11-16 no worktree do card:

    teste focal: 6 passed (3 novos: sticky apos promote, sticky antes do
      bloqueio, trip plano apos promote; 1 positivo: comentario/prioridade
      depois do bloqueio continuam re-despachando)
    repro anexado pelo guardiao (test_repro_sticky.py): base 0965fb7c20 FALHA
      "C2 anulou trip sticky do disjuntor"; com o conserto PASSA
    mutantes.sh: 11/11 mortos (M8 = versao velha sem o guarda)

## Medir depois — NAO MEDIDO

Depende de merge (pela vigia) e reinicio do gateway com o codigo novo. Medir
com `python baseline.py ~/.hermes/kanban/boards/atlas/kanban.db`. O C2
funcionando aparece como `auto_redespacho_eventos > 0` e `retomados_auto > 0`,
com `latencia_auto_min_mediana` perto de `transient_redispatch_seconds`/60
(padrao 600 s, mais o intervalo do tick). O corpo do card pede "medir antes e
depois"; nao fixa meta numerica de latencia.
