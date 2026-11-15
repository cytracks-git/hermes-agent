"""Prova viva C2 sobre COPIA do board atlas (o original nao e tocado).

Em uma copia do kanban.db: cria um card, bloqueia transient, envelhece o evento,
roda dispatch_once real com spawn_fn espiao (nenhum worker sobe) e mede.
Controle negativo: mesmo fluxo com needs_input nao volta.
"""
import json, os, shutil, sqlite3, sys, tempfile
from pathlib import Path

WT = sys.argv[1]
sys.path.insert(0, WT)
src = Path("/Users/farantes/.hermes/kanban/boards/atlas/kanban.db")
tmp = Path(tempfile.mkdtemp(prefix="c2-prova-", dir=os.environ.get("TMPDIR")))
home = tmp / ".hermes"; (home / "kanban").mkdir(parents=True)
# backup online consistente (WAL incluso), sem escrever no original
with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(home / "kanban.db") as d:
    s.backup(d)
(home / "config.yaml").write_text("kanban:\n  transient_redispatch_seconds: 600\n")
os.environ["HERMES_HOME"] = str(home)
# HERMES_KANBAN_DB e o caminho cercado pelo guarda de delegacao: nao reapontar.
# A copia vive fora de ~/.hermes e e achada via HERMES_HOME.
os.environ.pop("HERMES_KANBAN_DB", None)
os.environ.pop("HERMES_KANBAN_BOARD", None)

from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_dispatch as kbd
from hermes_cli import profiles
profiles.profile_exists = lambda n: True

conn = kbc.connect()
print("db_copia:", conn.execute("PRAGMA database_list").fetchone()[2])
antes = conn.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status").fetchall()
print("antes:", dict((r[0], r[1]) for r in antes))
t_ok = kb.create_task(conn, title="C2 prova transient", assignee="executor")
t_neg = kb.create_task(conn, title="C2 controle needs_input", assignee="executor")
for t, k in ((t_ok, "transient"), (t_neg, "needs_input")):
    kb.claim_task(conn, t)
    kb.block_task(conn, t, reason=f"prova C2 {k}: bun install falhou", kind=k)
conn.execute("UPDATE task_events SET created_at = created_at - 700 WHERE task_id IN (?, ?)", (t_ok, t_neg))
conn.commit()
spawned = []
res = kbd.dispatch_once(conn, spawn_fn=lambda task, ws, board=None: spawned.append(task.id), max_spawn=0)
print("transient_redispatched:", res.transient_redispatched)
for t in (t_ok, t_neg):
    ev = conn.execute("SELECT kind, payload FROM task_events WHERE task_id=? ORDER BY id DESC LIMIT 1", (t,)).fetchone()
    print(t, kb.get_task(conn, t).status, ev[0], ev[1])
print("handoff_no_contexto:", "prova C2 transient: bun install falhou" in kb.build_worker_context(conn, t_ok))
outros = [x for x in res.transient_redispatched if x not in (t_ok,)]
print("cards_reais_retomados_na_copia:", outros)
conn.close()
shutil.rmtree(tmp)
print("copia_removida:", not tmp.exists())
