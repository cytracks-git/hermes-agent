"""Controle negativo do card t_78aaa333, pelo runner CANONICO.

Substitui os controles anteriores, que chamavam `pytest` cru e liam o rc de um
`tail` -- H1 recusou os dois vicios. Aqui cada rodada passa por
`harness/prova.sh`, que invoca `scripts/run_tests.sh` e grava o rc REAL em
arquivo; o veredito le esse arquivo, nunca a saida de um pipe.

Metodo: sabota UMA guarda, roda a suite que deveria protege-la, e exige rc != 0.
Uma sabotagem que passa em verde significa que a guarda nao esta medida -- e um
defeito do teste, nao um detalhe. Cada sabotagem e desfeita antes da proxima, e
a rodada final reexecuta tudo para provar que a restauracao voltou ao verde.

Roda sobre /work (copia gravavel); o worktree fica somente-leitura em /src.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile

RAIZ = pathlib.Path("/work")
HARNESS = RAIZ / "docs/evidencia/t_78aaa333/harness"
SAIDA = pathlib.Path("/saida/negativo")

KB = RAIZ / "hermes_cli/kanban_db.py"
KD = RAIZ / "hermes_cli/kanban_db_dispatch.py"
KA = RAIZ / "hermes_cli/kanban_db_approvals.py"
PA = RAIZ / "plugins/kanban/dashboard/plugin_api.py"
FW = RAIZ / "tools/file_approval_worker.py"

SUITE_NUCLEO = "tests/hermes_cli/test_kanban_approval_wait.py"
SUITE_DASH = "tests/plugins/test_kanban_dashboard_plugin.py"
SUITE_ARQUIVOS = "tests/tools/test_file_approval_worker.py"


def roda(alvos: list[str], rotulo: str) -> tuple[int, list[str]]:
    """Executa prova.sh; devolve (rc REAL lido do arquivo, ids de falha)."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as fh:
        fh.write("\n".join(alvos) + "\n")
        lista = fh.name
    subprocess.run(
        ["sh", str(HARNESS / "prova.sh"), str(RAIZ), lista, str(SAIDA), rotulo],
        capture_output=True, text=True)
    rc_f = SAIDA / f"{rotulo}.rc"
    ids_f = SAIDA / f"{rotulo}.ids"
    rc = int(rc_f.read_text().strip()) if rc_f.exists() else -1
    ids = [x for x in ids_f.read_text().splitlines() if x] if ids_f.exists() else []
    return rc, ids


# (rotulo, arquivo, trecho original, trecho sabotado, suites que devem acusar)
SABOTAGENS = [
    ("N12 revalidacao da preimagem/symlink some antes da escrita",
     FW,
     "                revalidate(payload)\n",
     "                pass  # mutante: preimagem e symlink ignorados\n",
     [SUITE_ARQUIVOS]),
    ("N1 pause mantem o claim: a espera humana ocupa vaga do orcamento",
     KB,
     "               SET status            = 'waiting_approval',\n"
     "                   claim_lock        = NULL,",
     "               SET status            = 'waiting_approval',\n"
     "                   claim_lock        = claim_lock,",
     [SUITE_NUCLEO]),

    ("N2 resume nao restaura identidade no mesmo CAS (running + claim NULL)",
     KB,
     "               SET status            = 'running',\n"
     "                   claim_lock        = ?,",
     "               SET status            = 'running',\n"
     "                   claim_lock        = NULL,",
     [SUITE_NUCLEO]),

    ("N3 pause encerra o run (habilitaria reap_terminal_workers a matar quem espera)",
     KB,
     '            "UPDATE task_runs SET approval_paused_at = ? WHERE id = ? AND ended_at IS NULL",',
     '            "UPDATE task_runs SET approval_paused_at = ?, ended_at = ? WHERE id = ?",',
     [SUITE_NUCLEO]),

    ("N4 enforce_max_runtime para de descontar a espera humana (T-3)",
     KD,
     'elapsed = now - int(row["active_started_at"]) - int(\n'
     '            _kb._row_get(row, "approval_wait_seconds") or 0)',
     'elapsed = now - int(row["active_started_at"])',
     [SUITE_NUCLEO]),

    ("N5 unicidade de pendencia deixa de ser UNIQUE (U-3)",
     KA,
     "CREATE UNIQUE INDEX IF NOT EXISTS idx_appr_one_pending_per_run",
     "CREATE INDEX IF NOT EXISTS idx_appr_one_pending_per_run",
     [SUITE_NUCLEO]),

    ("N6 varredura de orfas ignora consumed nao-aplicada (R-7)",
     KA,
     "(PENDING, GRANTED, CONSUMED)",
     "(PENDING, GRANTED)",
     [SUITE_NUCLEO]),

    ("N7 E-8 camada 1: clausula de origem some do UPDATE (a unica sem TOCTOU)",
     PA,
     '"WHERE id = ? AND status != \'waiting_approval\'",',
     '"WHERE id = ?",',
     [SUITE_DASH]),

    ("N8 E-8 camada 2: _apply_status para de olhar a origem",
     PA,
     "    current = kanban_db.get_task(conn, task_id)\n"
     "    if current is not None and current.status == \"waiting_approval\":\n"
     "        raise _StatusRejected(_WAITING_APPROVAL_ORIGIN_MSG)\n",
     "",
     [SUITE_DASH]),

    ("N9 entrada em waiting_approval por verbo generico volta a ser aceita",
     PA,
     '    if s == "waiting_approval":\n',
     '    if s == "zzz_nunca":\n',
     [SUITE_DASH]),

    ("N10 um verbo generico passa a LEVAR para waiting_approval",
     PA,
     '    "triage": lambda conn, tid, p: _drag_to(conn, tid, "triage")}',
     '    "triage": lambda conn, tid, p: _drag_to(conn, tid, "triage"),\n'
     '    "waiting_approval": lambda conn, tid, p: _drag_to(conn, tid, "waiting_approval")}',
     [SUITE_DASH]),

    ("N11 coluna waiting_approval some do board (E-2)",
     PA,
     '    "triage", "todo", "scheduled", "ready", "running", "waiting_approval",\n'
     '    "blocked", "review", "done",\n',
     '    "triage", "todo", "scheduled", "ready", "running",\n'
     '    "blocked", "review", "done",\n',
     [SUITE_DASH]),
]


def main() -> int:
    SAIDA.mkdir(parents=True, exist_ok=True)
    todas = [SUITE_NUCLEO, SUITE_DASH, SUITE_ARQUIVOS]

    rc, ids = roda(todas, "base")
    print(f"=== BASE (sem sabotagem): rc={rc} falhas={len(ids)}")
    if rc != 0:
        print("BASE VERMELHA -- controle negativo nao e interpretavel")
        for i in ids:
            print(f"    {i}")
        return 1

    problemas: list[str] = []
    for n, (rotulo, arq, antes, depois, suites) in enumerate(SABOTAGENS, 1):
        original = arq.read_text()
        if antes not in original:
            print(f"\n--- {rotulo}\n    SABOTAGEM INVALIDA: trecho ausente em {arq.name}")
            problemas.append(f"{rotulo} [trecho ausente]")
            continue
        arq.write_text(original.replace(antes, depois, 1))
        try:
            rc, ids = roda(suites, f"sab{n:02d}")
            veredito = "ACUSOU" if rc != 0 else "PASSOU EM SILENCIO <<< PROBLEMA"
            print(f"\n--- {rotulo}\n    rc={rc} falhas={len(ids)} -> {veredito}")
            for i in ids[:4]:
                print(f"      {i}")
            if rc == 0:
                problemas.append(rotulo)
        finally:
            arq.write_text(original)

    rc, ids = roda(todas, "restaurado")
    print(f"\n=== RESTAURADO: rc={rc} falhas={len(ids)}")
    if rc != 0:
        print("A restauracao nao voltou ao verde -- medicao invalida")
        return 1
    if problemas:
        print("\nSABOTAGENS NAO DETECTADAS (guardas sem teste com dente):")
        for x in problemas:
            print(f"  - {x}")
        return 1
    print(f"\nTODAS as {len(SABOTAGENS)} sabotagens foram acusadas, com rc real do runner canonico.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
