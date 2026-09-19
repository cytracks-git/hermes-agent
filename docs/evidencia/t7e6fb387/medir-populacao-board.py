"""Medir a populacao REAL do board antes de escolher o predicado de conserto.

Nao altera nada. So le o banco de producao e o disco.
"""
from __future__ import annotations

import os
import re
import sqlite3
import subprocess
from pathlib import Path

DB = Path.home() / ".hermes/kanban/boards/atlas/kanban.db"
WSROOT = Path.home() / ".hermes/kanban/boards/atlas/workspaces"

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row


def q(sql, *a):
    return conn.execute(sql, a).fetchall()


print("=" * 72)
print("A) FALHA 3 — scratch dirs: o que o rmtree apagaria hoje")
print("=" * 72)
rows = q("SELECT id, status, workspace_kind, workspace_path FROM tasks "
         "WHERE workspace_kind='scratch' AND workspace_path IS NOT NULL")
vazio = com_arq = sem_dir = 0
com_arquivos = []
for r in rows:
    p = Path(r["workspace_path"]).expanduser()
    if not p.is_dir():
        sem_dir += 1
        continue
    arquivos = [f for f in p.rglob("*") if f.is_file()]
    if not arquivos:
        vazio += 1
    else:
        com_arq += 1
        tot = sum(f.stat().st_size for f in arquivos)
        com_arquivos.append((r["id"], r["status"], len(arquivos), tot))
print(f"scratch com workspace_path : {len(rows)}")
print(f"  dir nao existe (ja apagado): {sem_dir}")
print(f"  dir VAZIO                  : {vazio}")
print(f"  dir COM arquivos           : {com_arq}")
com_arquivos.sort(key=lambda t: -t[3])
print("\n  top 10 por bytes (id, status, n_arquivos, bytes):")
for t in com_arquivos[:10]:
    print(f"    {t[0]}  {t[1]:<9} {t[2]:>5} arq  {t[3]:>12,} B")

print()
print("Desses COM arquivos, quantos estao DONE (ou seja: o rmtree ja rodou ou vai rodar)?")
done_com = [t for t in com_arquivos if t[1] == "done"]
print(f"  done com arquivos ainda no disco: {len(done_com)}")

print()
print("Quantos cards tem attachment registrado (= entregou por canal duravel)?")
try:
    att = q("SELECT task_id, count(*) c FROM task_attachments GROUP BY task_id")
    ids_att = {a["task_id"] for a in att}
except sqlite3.Error as e:
    ids_att = set()
    print("  (sem tabela task_attachments:", e, ")")
print(f"  cards com attachment: {len(ids_att)}")
so_arq_sem_att = [t for t in com_arquivos if t[0] not in ids_att]
print(f"  scratch COM arquivos e SEM attachment: {len(so_arq_sem_att)}")
print("  -> este seria o universo preservado por 'preserva se tem arquivo e nao tem attachment'")

print()
print("=" * 72)
print("B) FALHA 1 — descoberta de worktree sem metadata")
print("=" * 72)
runs = q("SELECT task_id, metadata FROM task_runs WHERE metadata IS NOT NULL AND metadata != ''")
import json
declara = 0
for r in runs:
    try:
        m = json.loads(r["metadata"])
    except Exception:
        continue
    if isinstance(m, dict) and any(k in m for k in
                                   ("worktree", "repo", "repo_path", "workspace", "worktree_path")):
        declara += 1
print(f"runs com metadata           : {len(runs)}")
print(f"  runs que DECLARAM um repo : {declara}")
print(f"  runs que CALAM            : {len(runs) - declara}")
print("  -> hoje so os que declaram sao medidos; os que calam passam.")

print()
print("Worktrees REAIS ligados aos repos que o board conhece, e se o task id aparece no path:")
# raizes conhecidas: workspace_path de qualquer card + o hermes-agent
cands = set()
for r in q("SELECT DISTINCT workspace_path FROM tasks WHERE workspace_path IS NOT NULL"):
    cands.add(Path(r["workspace_path"]).expanduser())
cands.add(Path.home() / ".hermes/hermes-agent")

roots = {}
for c in cands:
    if not c.is_dir():
        continue
    p = subprocess.run(["git", "-C", str(c), "rev-parse", "--path-format=absolute",
                        "--git-common-dir"], capture_output=True, text=True, timeout=20)
    if p.returncode == 0:
        roots[p.stdout.strip()] = c

print(f"  raizes git distintas alcancadas a partir do banco: {len(roots)}")
tids = [r["id"] for r in q("SELECT id FROM tasks")]
for common, anchor in roots.items():
    p = subprocess.run(["git", "-C", str(anchor), "worktree", "list", "--porcelain"],
                       capture_output=True, text=True, timeout=30)
    wts = [l.split(" ", 1)[1] for l in p.stdout.splitlines() if l.startswith("worktree ")]
    print(f"\n  repo {anchor}  ({len(wts)} worktrees)")
    for w in wts:
        casou = [t for t in tids if t in w or t.replace("_", "") in w]
        print(f"    {w}   casou_task_id={casou}")

print()
print("=" * 72)
print("C) FALHA 2 — URLs de remoto nos repos alcancados")
print("=" * 72)
for common, anchor in roots.items():
    p = subprocess.run(["git", "-C", str(anchor), "remote", "-v"],
                       capture_output=True, text=True, timeout=20)
    print(f"  {anchor}:")
    for l in p.stdout.splitlines()[:4]:
        print(f"    {l}")
