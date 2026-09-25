"""Custo do predicado por request contra o recorte global, medido.

Por que existe
--------------
Trocar uma leitura por outra sem medir seria afirmar desempenho por desenho --
o que a regra 11 chama de escolher o adjetivo confortavel. Esta sonda mede as
DUAS formas no MESMO banco, com o MESMO numero de linhas, e imprime:

  - o plano de consulta que o SQLite escolhe (prova se o indice e usado, ou
    se ``SCAN`` aparece);
  - o tempo de N leituras de cada forma.

Nao e benchmark de producao e nao pretende ser: e a comparacao lado a lado que
responde "o conserto custou caro?" com numero em vez de opiniao.

Uso: python3 sonda_custo_leitura.py [n_linhas] [n_leituras]
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from hermes_cli import kanban_approval_diagnostics as diag
from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect

# A forma antiga, preservada aqui SO como termo de comparacao. Nao ha copia
# dela no codigo de producao -- se um dia houver, e regressao.
ANTIGA = ("SELECT id, payload, created_at FROM task_events "
          " WHERE kind = ? ORDER BY id DESC LIMIT 200")


def _antiga(conn, request_id):
    for item in conn.execute(ANTIGA, (diag.PROGRESS_KIND,)).fetchall():
        payload = kb._json_or(item["payload"], {}) or {}
        if payload.get("request_id") == request_id:
            return payload
    return None


def main() -> int:
    linhas = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    leituras = int(sys.argv[2]) if len(sys.argv) > 2 else 200

    tmp = Path(tempfile.mkdtemp())
    conn = connect(kb.init_db(db_path=tmp / "custo.db"))
    tid = kb.create_task(conn, title="sonda custo", assignee="sonda")
    kb.recompute_ready(conn)
    task = kb.claim_task(conn, tid)

    alvo = "ap_alvo"
    passo = dict(task_id=tid, run_id=task.current_run_id, phase=diag.AWAITING_HUMAN,
                 reason_code=diag.HUMAN_DECISION_PENDING)
    diag.record_progress(conn, request_id=alvo, **passo)
    for n in range(linhas):
        diag.record_progress(conn, request_id=f"ap_irma_{n}", **passo)
    total = conn.execute("SELECT COUNT(*) AS c FROM task_events").fetchone()["c"]

    print(f"CUSTO linhas_em_task_events={total} leituras_por_forma={leituras}")

    plano = conn.execute(
        f"EXPLAIN QUERY PLAN SELECT id, payload, created_at FROM task_events "
        f"{diag._OF_REQUEST} ORDER BY id DESC LIMIT 1", (tid, diag.PROGRESS_KIND, alvo),
    ).fetchall()
    for row in plano:
        print(f"CUSTO plano_nova: {row['detail']}")
    for row in conn.execute(f"EXPLAIN QUERY PLAN {ANTIGA}", (diag.PROGRESS_KIND,)).fetchall():
        print(f"CUSTO plano_antiga: {row['detail']}")

    inicio = time.perf_counter()
    for _ in range(leituras):
        diag._last_progress(conn, tid, alvo)
    nova_ms = (time.perf_counter() - inicio) * 1000 / leituras

    inicio = time.perf_counter()
    for _ in range(leituras):
        _antiga(conn, alvo)
    antiga_ms = (time.perf_counter() - inicio) * 1000 / leituras

    # A antiga NAO encontra o alvo neste volume -- e o defeito, nao o custo.
    # Dizer o tempo sem dizer isso faria a leitura errada parecer barata.
    achou_antiga = _antiga(conn, alvo) is not None
    achou_nova = diag._last_progress(conn, tid, alvo) is not None

    print(f"CUSTO nova_ms_por_leitura={nova_ms:.3f} achou={achou_nova}")
    print(f"CUSTO antiga_ms_por_leitura={antiga_ms:.3f} achou={achou_antiga}")
    print(f"CUSTO razao_nova_sobre_antiga={nova_ms / antiga_ms:.2f}x")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
