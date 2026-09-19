#!/usr/bin/env python3
"""Mede, no board real, se `claim_lock` distingue autoria de revisao.

Contexto: no card t_ad873a37 quatro runs de revisao foram bloqueados porque o
worker leu `tasks.claim_lock` como "identidade de quem escreveu o codigo".
O campo tem a forma `<host>:<pid>` e esse pid e o do processo do GATEWAY --
avo de TODO worker do board, inclusive do proprio revisor. Este medidor mostra
o falso positivo e mostra o sinal que de fato responde "quem escreveu isto?".

Nao muta nada: abre o banco somente para leitura (modo ro).
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys


def abrir_ro(caminho: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{caminho}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def comando_do_pid(pid: int) -> str:
    """Devolve o argv do processo, ou um sentinela proprio.

    MORTO e ILEGIVEL sao bytes DIFERENTES de um comando real: "nao consegui
    ler" nunca pode ser confundido com "li e era isto".
    """
    try:
        saida = subprocess.run(
            ["ps", "-o", "command=", "-p", str(pid)],
            capture_output=True, text=True, timeout=10,
        )
    except Exception as exc:  # pragma: no cover - defensivo
        return f"<ILEGIVEL: {exc}>"
    if saida.returncode != 0 or not saida.stdout.strip():
        return "<MORTO>"
    return saida.stdout.strip().splitlines()[0]


def runs_do_card(conn: sqlite3.Connection, task_id: str) -> list[dict]:
    """Cruza task_runs com o pid REAL de cada run (evento `spawned`)."""
    eventos: dict[int, int] = {}
    for linha in conn.execute(
        "SELECT run_id, payload FROM task_events "
        "WHERE task_id = ? AND kind = 'spawned' AND run_id IS NOT NULL "
        "ORDER BY id", (task_id,),
    ):
        try:
            carga = json.loads(linha["payload"] or "{}")
        except (TypeError, ValueError):
            continue
        pid = carga.get("pid")
        if isinstance(pid, int):
            eventos[linha["run_id"]] = pid

    saida = []
    for linha in conn.execute(
        "SELECT id, profile, status, outcome FROM task_runs "
        "WHERE task_id = ? ORDER BY id", (task_id,),
    ):
        saida.append({
            "run_id": linha["id"],
            "profile": linha["profile"],
            "status": linha["status"],
            "outcome": linha["outcome"],
            "worker_pid": eventos.get(linha["id"]),
        })
    return saida


def locks_do_board(conn: sqlite3.Connection) -> dict[str, dict[str, set]]:
    """Para cada claim_lock visto em eventos, que perfis e cards ele serviu."""
    mapa: dict[str, dict[str, set]] = {}
    for linha in conn.execute(
        "SELECT e.task_id, e.run_id, e.payload, r.profile "
        "FROM task_events e LEFT JOIN task_runs r ON r.id = e.run_id "
        "WHERE e.kind = 'claimed'",
    ):
        try:
            lock = json.loads(linha["payload"] or "{}").get("lock")
        except (TypeError, ValueError):
            continue
        if not lock:
            continue
        entrada = mapa.setdefault(lock, {"perfis": set(), "cards": set(), "runs": set()})
        if linha["profile"]:
            entrada["perfis"].add(linha["profile"])
        entrada["cards"].add(linha["task_id"])
        if linha["run_id"] is not None:
            entrada["runs"].add(linha["run_id"])
    return mapa


def main() -> int:
    banco = os.environ.get("HERMES_KANBAN_DB")
    alvo = sys.argv[1] if len(sys.argv) > 1 else "t_ad873a37"
    if not banco or not os.path.exists(banco):
        print(f"NAO MEDIDO: HERMES_KANBAN_DB ausente ou inexistente ({banco!r})")
        return 2

    conn = abrir_ro(banco)

    print(f"== CARD MEDIDO: {alvo} ==")
    linha = conn.execute(
        "SELECT claim_lock, assignee, status FROM tasks WHERE id = ?", (alvo,),
    ).fetchone()
    if linha is None:
        print(f"NAO MEDIDO: card {alvo} nao existe neste board")
        return 2
    lock = linha["claim_lock"]
    print(f"tasks.claim_lock = {lock!r}   assignee={linha['assignee']}  status={linha['status']}")

    print("\n== 1. O QUE E O PID DO LOCK ==")
    if lock and ":" in str(lock):
        pid_txt = str(lock).rsplit(":", 1)[1]
        if pid_txt.isdigit():
            print(f"pid {pid_txt} -> {comando_do_pid(int(pid_txt))}")
        else:
            print(f"<sufixo do lock nao e pid: {pid_txt!r}>")
    else:
        print("<card sem claim_lock agora; o lock so existe enquanto o run esta vivo>")

    print("\n== 2. QUEM MAIS USOU ESSE MESMO LOCK (board inteiro) ==")
    mapa = locks_do_board(conn)
    alvo_lock = lock or os.environ.get("HERMES_KANBAN_CLAIM_LOCK")
    for nome, dados in sorted(mapa.items(), key=lambda kv: -len(kv[1]["runs"])):
        marca = "  <-- o do card" if nome == alvo_lock else ""
        print(f"{nome:24s} perfis={sorted(dados['perfis'])} runs={len(dados['runs'])} "
              f"cards={len(dados['cards'])}{marca}")

    print(f"\n== 3. AUTORIA x REVISAO NO {alvo}: PROCESSOS SAO OS MESMOS? ==")
    runs = runs_do_card(conn, alvo)
    for run in runs:
        print(f"run {run['run_id']:<5} {run['profile']:<10} {str(run['status']):<18} "
              f"outcome={str(run['outcome']):<18} worker_pid={run['worker_pid']}")
    pids = {r["worker_pid"] for r in runs if r["worker_pid"] is not None}
    perfis = {r["profile"] for r in runs if r["profile"]}
    print(f"\npids distintos: {len(pids)}   perfis distintos: {len(perfis)} {sorted(perfis)}")

    print("\n== VEREDITO ==")
    perfis_do_lock = mapa.get(alvo_lock or "", {}).get("perfis", set())
    if alvo_lock and len(perfis_do_lock) > 1:
        print(f"claim_lock {alvo_lock} serviu {sorted(mapa[alvo_lock]['perfis'])} -- "
              "ele NAO identifica autoria. Um worker que o compare com o proprio "
              "ancestral conclui 'sou eu' em QUALQUER run do board: falso positivo.")
    if len(pids) > 1:
        print(f"Os runs deste card rodaram em {len(pids)} processos distintos {sorted(pids)}: "
              "os assentos NAO estavam colapsados.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
