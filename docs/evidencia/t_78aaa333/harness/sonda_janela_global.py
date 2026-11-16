"""Medicao direta do achado do R3: a janela global de 200 perde a request.

Por que existe, alem da suite
-----------------------------
Na arvore ANTIGA, tres dos testes novos falham por assinatura (``notice_budget_open``
ganhou ``task_id``), nao pelo defeito -- e falha por assinatura nao prova defeito
nenhum. Esta sonda chama as funcoes de PRODUCAO com a assinatura que cada arvore
tem, aplica o MESMO estimulo e imprime o que foi OBSERVADO. Serve de controle
positivo do conserto: na arvore antiga tem de acusar, na nova tem de ficar limpa.

Estimulo, igual dos dois lados:
  1. uma observacao da request alvo;
  2. 210 observacoes de OUTRAS requests no mesmo card (a "carga");
  3. o mesmo poll da request alvo -- que nao deve gravar nada;
  4. um "Retry notice" humano da request alvo, seguido de 210 retries de outras;
     o orcamento da alvo tem de reabrir.

Uso: python3 sonda_janela_global.py <rotulo>
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from hermes_cli import kanban_approval_diagnostics as diag
from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect

ALVO = "ap_alvo"
IRMAS = 210


def _chamar(fn, conn, task_id, *resto):
    """Chama ``fn`` com ou sem ``task_id``, conforme a assinatura da arvore.

    E o unico jeito de aplicar o MESMO estimulo as duas versoes sem reescrever
    a sonda por arvore -- e sem esconder qual das duas esta rodando.
    """
    import inspect
    params = list(inspect.signature(fn).parameters)
    if "task_id" in params:
        return fn(conn, task_id, *resto)
    return fn(conn, *resto)


def main() -> int:
    rotulo = sys.argv[1] if len(sys.argv) > 1 else "sonda"
    tmp = Path(tempfile.mkdtemp())
    db = kb.init_db(db_path=tmp / "sonda.db")
    conn = connect(db)
    tid = kb.create_task(conn, title="sonda janela global", assignee="sonda")
    kb.recompute_ready(conn)
    task = kb.claim_task(conn, tid)
    run_id = task.current_run_id

    passo = dict(task_id=tid, run_id=run_id, phase=diag.AWAITING_HUMAN,
                 reason_code=diag.HUMAN_DECISION_PENDING)

    def linhas_da_alvo() -> list[int]:
        """Ids das observacoes da request alvo, lidos SEM o predicado sob teste."""
        out = []
        for row in conn.execute("SELECT id, payload FROM task_events WHERE kind = ? ORDER BY id",
                                (diag.PROGRESS_KIND,)).fetchall():
            if (kb._json_or(row["payload"], {}) or {}).get("request_id") == ALVO:
                out.append(int(row["id"]))
        return out

    diag.record_progress(conn, request_id=ALVO, **passo)
    antes = linhas_da_alvo()
    for n in range(IRMAS):
        diag.record_progress(conn, request_id=f"ap_irma_{n}", **passo)
    gravou = diag.record_progress(conn, request_id=ALVO, **passo)
    depois = linhas_da_alvo()

    print(f"{rotulo} DEDUPE alvo_antes={antes}")
    print(f"{rotulo} DEDUPE poll_identico_gravou={bool(gravou)}")
    print(f"{rotulo} DEDUPE alvo_depois={depois}")
    print(f"{rotulo} DEDUPE PERDEU_A_REQUEST={len(depois) > len(antes)}")

    # --- marca d'agua do "Retry notice" -----------------------------------
    diag.record_notice_outcome(conn, task_id=tid, run_id=run_id, request_id=ALVO,
                               generation="gen-1", delivered=False, limit=1)
    fechado = not _chamar(diag.notice_budget_open, conn, tid, ALVO, "gen-1", 1)
    diag.request_notice_retry(conn, task_id=tid, run_id=run_id, request_id=ALVO)
    for n in range(IRMAS):
        diag.request_notice_retry(conn, task_id=tid, run_id=run_id,
                                  request_id=f"ap_irma_{n}")
    reabriu = _chamar(diag.notice_budget_open, conn, tid, ALVO, "gen-1", 1)

    print(f"{rotulo} RETRY esgotou_antes_do_retry={fechado}")
    print(f"{rotulo} RETRY reabriu_apos_retry_humano={bool(reabriu)}")
    print(f"{rotulo} RETRY PERDEU_O_RETRY={not reabriu}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
