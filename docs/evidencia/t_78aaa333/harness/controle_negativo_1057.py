"""Controle negativo do recorte 1057/1058 (diagnostico contextual), card t_78aaa333.

Mesmo metodo de `controle_negativo.py`, aplicado as guardas NOVAS: sabota uma
por vez, roda pelo runner CANONICO via `harness/prova.sh` e exige rc != 0 lido
de ARQUIVO (nunca de pipe). Uma sabotagem que passa em verde significa guarda
sem dente -- defeito do teste, nao detalhe.

As sabotagens cobrem exatamente as decisoes que o H1 vetou ou exigiu:

  M1/M2  observacao voltaria a nascer do relogio (1058 proibiu alarme por tempo)
  M3     `granted` parado viraria "capacidade cheia" sem ter medido
  M4     orcamento de aviso viraria "tentar para sempre"
  M5     orcamento deixaria de ser por geracao de transporte
  M6     "Retry notice" humano deixaria de reabrir o orcamento
  M7     diagnostico viraria notificacao e acordaria modelo
  M8/M9  leitura voltaria a janela global de 200 (o achado do R3): a dedupe
         ficaria cega sob carga e o retry humano se perderia atras de outras
         requests
  M10    indice novo sumiria na reconstrucao de board legado (DROP TABLE leva
         os indices junto), degradando calado quem ja tem board antigo

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
CONNECT = RAIZ / "hermes_cli/kanban_db_connect.py"

SUITE_DIAG = "tests/hermes_cli/test_kanban_approval_diagnostics.py"
SUITE_POLLER = "tests/tui_gateway/test_kanban_notify_poller.py"
SUITE_DB = "tests/hermes_cli/test_kanban_db.py"


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
     "    return notice_attempts(conn, task_id, request_id, generation) < cap",
     "    return True  # mutante: tenta para sempre",
     [SUITE_DIAG, SUITE_POLLER]),

    ("M5 orcamento deixa de ser por geracao (reconexao herda esgotamento)",
     DIAG,
     "        f\"   AND json_extract({_PAYLOAD}, '$.generation') = ? \"\n",
     "        f\"   AND ? IS NOT NULL \"  # mutante: geracao ignorada\n",
     [SUITE_DIAG]),

    ("M6 retry humano para de reabrir o orcamento",
     DIAG,
     "    floor = _notice_retry_marker(conn, task_id, request_id)\n"
     "    row = conn.execute(\n"
     '        f"SELECT COUNT(*) AS total FROM task_events {_OF_REQUEST} AND id > ? "\n',
     "    floor = 0  # mutante: marca d'agua do retry ignorada\n"
     "    row = conn.execute(\n"
     '        f"SELECT COUNT(*) AS total FROM task_events {_OF_REQUEST} AND id > ? "\n',
     [SUITE_DIAG]),

    ("M7 diagnostico entra na lista de notificacao (acordaria modelo)",
     NOTIF,
     '_KANBAN_NOTIFY_KINDS = ("completed", "blocked", "gave_up", "crashed", "timed_out", '
     '"status", "archived", "unblocked", "approval_requested")',
     '_KANBAN_NOTIFY_KINDS = ("completed", "blocked", "gave_up", "crashed", "timed_out", '
     '"status", "archived", "unblocked", "approval_requested", "approval_progress")',
     [SUITE_DIAG]),

    # M8 reintroduz EXATAMENTE o defeito que o R3 achou na rodada anterior: o
    # recorte global de 200 no lugar do predicado por request. Ele passava em
    # verde com poucas observacoes no banco -- so aparece sob carga -- entao os
    # testes que o acusam sao os que criam 210 irmas. Sem esta sabotagem, o
    # controle negativo continuaria sendo "detector que nao mede o que nao
    # lista", que foi o diagnostico do proprio R3.
    ("M8 leitura volta a janela global de 200 (dedupe cega sob carga)",
     DIAG,
     '    sql = (f"SELECT id, payload, created_at FROM task_events {_OF_REQUEST}"\n'
     "           + (f\" AND json_extract({_PAYLOAD}, '$.phase') IS NOT ? \" if exclude_notice else \"\")\n"
     '           + " ORDER BY id DESC LIMIT 1")\n'
     "    args: tuple = (task_id, PROGRESS_KIND, request_id)\n"
     "    if exclude_notice:\n"
     "        args += (NOTICE,)\n"
     "    row = conn.execute(sql, args).fetchone()\n"
     "    if row is None:\n"
     "        return None\n"
     '    payload = kb._json_or(row["payload"], {}) or {}\n'
     '    return {"id": int(row["id"]), "created_at": int(row["created_at"]), **payload}\n',
     "    # mutante: recorte global, request_id filtrado depois em Python\n"
     "    rows = conn.execute(\n"
     '        "SELECT id, payload, created_at FROM task_events "\n'
     '        " WHERE kind = ? ORDER BY id DESC LIMIT 200", (PROGRESS_KIND,),\n'
     "    ).fetchall()\n"
     "    for item in rows:\n"
     '        payload = kb._json_or(item["payload"], {}) or {}\n'
     '        if payload.get("request_id") != request_id:\n'
     "            continue\n"
     '        if exclude_notice and payload.get("phase") == NOTICE:\n'
     "            continue\n"
     '        return {"id": int(item["id"]), "created_at": int(item["created_at"]), **payload}\n'
     "    return None\n",
     [SUITE_DIAG]),

    # M9 e o irmao de M8 na marca d'agua do retry: mesma classe de defeito,
    # outro ponto de leitura. Separado porque um conserto parcial (so o
    # _last_progress) passaria no M8 e deixaria o aviso humano preso.
    ("M9 marca d'agua do retry volta a janela global de 200",
     DIAG,
     "    row = conn.execute(\n"
     '        f"SELECT id FROM task_events {_OF_REQUEST} ORDER BY id DESC LIMIT 1",\n'
     "        (task_id, NOTICE_RETRY_KIND, request_id),\n"
     "    ).fetchone()\n"
     '    return int(row["id"]) if row is not None else 0\n',
     "    rows = conn.execute(  # mutante: janela global\n"
     '        "SELECT id, payload FROM task_events WHERE kind = ? ORDER BY id DESC LIMIT 200",\n'
     "        (NOTICE_RETRY_KIND,),\n"
     "    ).fetchall()\n"
     "    for item in rows:\n"
     '        payload = kb._json_or(item["payload"], {}) or {}\n'
     '        if payload.get("request_id") == request_id:\n'
     '            return int(item["id"])\n'
     "    return 0\n",
     [SUITE_DIAG]),

    # M10 nao e do recorte 1057: e do indice que o conserto exigiu. Como
    # ``DROP TABLE`` leva os indices junto, um indice novo no SCHEMA_SQL que
    # nao seja repetido no _REBUILD_SPECS some calado em board legado
    # reconstruido -- perda de desempenho que ninguem ve. Os tres comentarios
    # que prometiam um guardiao para isso citavam um teste que NAO EXISTIA;
    # esta sabotagem e a prova de que agora existe e tem dente.
    ("M10 indice novo some da reconstrucao de board legado",
     CONNECT,
     '            "CREATE INDEX idx_events_task_kind ON task_events(task_id, kind, id)",\n',
     "",
     [SUITE_DB]),
]


def main() -> int:
    SAIDA.mkdir(parents=True, exist_ok=True)
    todas = [SUITE_DIAG, SUITE_POLLER, SUITE_DB]

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
