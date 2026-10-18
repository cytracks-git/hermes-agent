"""O indice custa quanto na ESCRITA e em ESPACO? Medido.

Contexto
--------
A sonda do indice provou o ganho na leitura (0,603 -> 0,007 ms num card de
1.4 mil eventos). Ganho de leitura sem o custo do outro lado e meia verdade:
todo indice se paga na escrita e em bytes, e ``task_events`` e tabela de
append -- cada evento de cada card passa por ela.

Esta sonda grava o MESMO numero de eventos com e sem o indice, no mesmo
processo, e mede:

  - ms por INSERT (via record_progress, o caminho real de producao);
  - bytes do banco e paginas do indice (dbstat quando disponivel).

Uso: python3 sonda_custo_escrita.py [n_eventos]
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from hermes_cli import kanban_approval_diagnostics as diag
from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect

INDICE = "idx_events_task_kind"


def _tamanho(conn, path: Path) -> tuple[int, int]:
    """(bytes do arquivo, bytes do indice). 0 no indice se dbstat faltar."""
    conn.commit()
    total = path.stat().st_size
    try:
        row = conn.execute(
            "SELECT SUM(pgsize) AS b FROM dbstat WHERE name = ?", (INDICE,)).fetchone()
        return total, int(row["b"] or 0)
    except Exception:
        # dbstat e modulo opcional do SQLite; sem ele, digo 0 em vez de
        # inventar uma estimativa.
        return total, 0


def medir(rotulo: str, eventos: int, com_indice: bool) -> None:
    tmp = Path(tempfile.mkdtemp())
    caminho = tmp / "escrita.db"
    conn = connect(kb.init_db(db_path=caminho))
    if not com_indice:
        conn.execute(f"DROP INDEX IF EXISTS {INDICE}")
    tid = kb.create_task(conn, title="sonda escrita", assignee="sonda")
    kb.recompute_ready(conn)
    task = kb.claim_task(conn, tid)
    passo = dict(task_id=tid, run_id=task.current_run_id, phase=diag.AWAITING_HUMAN,
                 reason_code=diag.HUMAN_DECISION_PENDING)

    inicio = time.perf_counter()
    for n in range(eventos):
        diag.record_progress(conn, request_id=f"req_{n}", **passo)
    ms = (time.perf_counter() - inicio) * 1000 / eventos

    arquivo, indice = _tamanho(conn, caminho)
    print(f"ESCRITA {rotulo} ms_por_insert={ms:.4f} bytes_db={arquivo} "
          f"bytes_indice={indice}")
    conn.close()


def main() -> int:
    eventos = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    print(f"ESCRITA eventos_por_rodada={eventos}")
    medir("SEM_INDICE", eventos, com_indice=False)
    medir("COM_INDICE", eventos, com_indice=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
