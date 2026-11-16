"""O indice candidato paga o predicado por request? Medido, nao suposto.

Contexto
--------
A primeira medicao (``sonda_custo_leitura.py``) mostrou que ``idx_events_task``
(task_id, created_at) NAO serve o ``ORDER BY id``: o SQLite resolve com
``USE TEMP B-TREE FOR ORDER BY``, que ordena TODAS as linhas do card a cada
leitura. No board real da Atlas o maior card tem ~1.4 mil eventos, entao isso
nao e hipotese distante: e o tamanho de hoje.

Esta sonda mede a MESMA consulta antes e depois de criar
``idx_events_task_kind(task_id, kind, id)``, no mesmo processo e no mesmo
banco. Serve de controle positivo do indice: se o plano nao mudar, o indice e
decoracao e nao deve ser criado.

Uso: python3 sonda_indice_candidato.py [n_linhas] [n_leituras]
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from hermes_cli import kanban_approval_diagnostics as diag
from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect

INDICE = "CREATE INDEX IF NOT EXISTS idx_events_task_kind ON task_events(task_id, kind, id)"


def medir(conn, tid: str, rotulo: str, leituras: int) -> None:
    sql = (f"SELECT id, payload, created_at FROM task_events {diag._OF_REQUEST} "
           f" ORDER BY id DESC LIMIT 1")
    for row in conn.execute(f"EXPLAIN QUERY PLAN {sql}",
                            (tid, diag.PROGRESS_KIND, "alvo")).fetchall():
        print(f"{rotulo} plano: {row['detail']}")
    inicio = time.perf_counter()
    for _ in range(leituras):
        diag._last_progress(conn, tid, "alvo")
    print(f"{rotulo} ms_por_leitura={(time.perf_counter() - inicio) * 1000 / leituras:.3f}")


def main() -> int:
    linhas = int(sys.argv[1]) if len(sys.argv) > 1 else 1400
    leituras = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    # ``fim`` = a request alvo e a MAIS RECENTE do card (o caso de producao: o
    # worker consulta a espera que esta acontecendo agora). ``inicio`` = a mais
    # antiga, o pior caso possivel, porque ``ORDER BY id DESC`` percorre todas
    # as irmas antes de chegar nela. Medir so um dos dois daria um numero
    # escolhido, nao medido.
    posicao = sys.argv[3] if len(sys.argv) > 3 else "fim"

    tmp = Path(tempfile.mkdtemp())
    conn = connect(kb.init_db(db_path=tmp / "indice.db"))
    tid = kb.create_task(conn, title="sonda indice", assignee="sonda")
    kb.recompute_ready(conn)
    task = kb.claim_task(conn, tid)
    passo = dict(task_id=tid, run_id=task.current_run_id, phase=diag.AWAITING_HUMAN,
                 reason_code=diag.HUMAN_DECISION_PENDING)
    if posicao == "inicio":
        diag.record_progress(conn, request_id="alvo", **passo)
    for n in range(linhas):
        diag.record_progress(conn, request_id=f"irma_{n}", **passo)
    if posicao != "inicio":
        diag.record_progress(conn, request_id="alvo", **passo)
    print(f"INDICE linhas={conn.execute('SELECT COUNT(*) c FROM task_events').fetchone()['c']} "
          f"leituras={leituras} posicao_do_alvo={posicao}")

    ja_existe = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_events_task_kind'"
    ).fetchone() is not None
    print(f"INDICE ja_criado_pelo_schema={bool(ja_existe)}")
    if ja_existe:
        # A arvore ja traz o indice: para medir o ANTES e preciso remove-lo
        # deste banco descartavel. Sem isso a comparacao seria contra si mesma.
        conn.execute("DROP INDEX idx_events_task_kind")

    medir(conn, tid, "SEM_INDICE", leituras)
    conn.execute(INDICE)
    medir(conn, tid, "COM_INDICE", leituras)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
