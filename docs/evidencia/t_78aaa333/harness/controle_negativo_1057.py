"""Controle negativo do recorte 1057/1058 (diagnostico contextual), card t_78aaa333.

Mesmo metodo de `controle_negativo.py`, aplicado as guardas NOVAS: sabota uma
por vez, roda pelo runner CANONICO via `harness/prova.sh` e exige rc != 0 lido
de ARQUIVO (nunca de pipe). Uma sabotagem que passa em verde significa guarda
sem dente -- defeito do teste, nao detalhe.

As sete sabotagens cobrem exatamente as decisoes que o H1 vetou ou exigiu:

  M1/M2  observacao voltaria a nascer do relogio (1058 proibiu alarme por tempo)
  M3     `granted` parado viraria "capacidade cheia" sem ter medido
  M4     orcamento de aviso viraria "tentar para sempre"
  M5     orcamento deixaria de ser por geracao de transporte
  M6     "Retry notice" humano deixaria de reabrir o orcamento
  M7     diagnostico viraria notificacao e acordaria modelo

Roda sobre /work (copia gravavel); o worktree fica somente-leitura em /src.
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile

RAIZ = pathlib.Path("/work")
HARNESS = RAIZ / "docs/evidencia/t_78aaa333/harness"
SAIDA = pathlib.Path("/saida/negativo-1057")

DIAG = RAIZ / "hermes_cli/kanban_approval_diagnostics.py"
NOTIF = RAIZ / "tui_gateway/session_notifications.py"

SUITE_DIAG = "tests/hermes_cli/test_kanban_approval_diagnostics.py"
SUITE_POLLER = "tests/tui_gateway/test_kanban_notify_poller.py"


def roda(alvos: list[str], rotulo: str) -> tuple[int, list[str]]:
    """Executa prova.sh; devolve (rc REAL lido do arquivo, ids de falha)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
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
    ("M1 deduplicacao ignora a etapa: qualquer poll grava linha nova",
     DIAG,
     '            previous.get("phase") == phase\n',
     '            True  # mutante: etapa deixa de ser criterio\n',
     [SUITE_DIAG]),

    ("M2 deduplicacao some de vez (observacao nasce do relogio)",
     DIAG,
     "    if previous is not None and (",
     "    if False and previous is not None and (",
     [SUITE_DIAG]),

    ("M3 granted sem observacao passa a alegar capacidade cheia",
     DIAG,
     "        return AWAITING_ADMISSION, RESUME_REASON_NOT_YET_OBSERVED",
     "        return AWAITING_ADMISSION, HOST_CAPACITY",
     [SUITE_DIAG]),

    ("M4 orcamento de aviso vira ilimitado (martela conexao morta)",
     DIAG,
     "    return notice_attempts(conn, request_id, generation) < cap",
     "    return True  # mutante: tenta para sempre",
     [SUITE_DIAG, SUITE_POLLER]),

    ("M5 orcamento deixa de ser por geracao (reconexao herda esgotamento)",
     DIAG,
     '                and payload.get("generation") == generation\n',
     "                and True  # mutante: geracao ignorada\n",
     [SUITE_DIAG]),

    ("M6 retry humano para de reabrir o orcamento",
     DIAG,
     "    floor = _notice_retry_marker(conn, request_id)\n"
     '    rows = conn.execute(\n'
     '        "SELECT id, payload FROM task_events WHERE kind = ? AND id > ? ORDER BY id ASC",\n'
     "        (PROGRESS_KIND, floor),\n"
     "    ).fetchall()\n"
     "    total = 0\n",
     "    floor = 0  # mutante: marca d'agua do retry ignorada\n"
     '    rows = conn.execute(\n'
     '        "SELECT id, payload FROM task_events WHERE kind = ? AND id > ? ORDER BY id ASC",\n'
     "        (PROGRESS_KIND, floor),\n"
     "    ).fetchall()\n"
     "    total = 0\n",
     [SUITE_DIAG]),

    ("M7 diagnostico entra na lista de notificacao (acordaria modelo)",
     NOTIF,
     '_KANBAN_NOTIFY_KINDS = ("completed", "blocked", "gave_up", "crashed", "timed_out", '
     '"status", "archived", "unblocked", "approval_requested")',
     '_KANBAN_NOTIFY_KINDS = ("completed", "blocked", "gave_up", "crashed", "timed_out", '
     '"status", "archived", "unblocked", "approval_requested", "approval_progress")',
     [SUITE_DIAG]),
]


def main() -> int:
    SAIDA.mkdir(parents=True, exist_ok=True)
    todas = [SUITE_DIAG, SUITE_POLLER]

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
            rc, ids = roda(suites, f"mut{n:02d}")
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
