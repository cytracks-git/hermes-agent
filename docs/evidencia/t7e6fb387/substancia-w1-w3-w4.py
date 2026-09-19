"""W1/W3/W4 do revisor: o que MUDOU de verdade, alem do status do card.

O harness do revisor so olha `status == done`. Isso e grosso demais para dois
dos tres casos: o card FECHAR pode estar certo e o defeito real ser outro (o
trabalho sumir, a forja ficar invisivel). Aqui eu meco a substancia.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/Users/farantes/atlas/wt/t7e6fb387-direto")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolar_board import isolar_board  # noqa: E402

RAIZ = isolar_board("substancia-w-")

from hermes_cli import kanban_db as kb          # noqa: E402
from hermes_cli import kanban_db_connect as kbc  # noqa: E402
from hermes_cli import kanban_db_workspace as kbw  # noqa: E402

kb._INITIALIZED_PATHS.clear()
kb.init_db()


def git(*a, cwd=None):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"git {' '.join(a)}: {r.stderr}"
    return r.stdout


def origem_e_clone(root: Path, nome="project"):
    origin = root / f"{nome}-origin.git"
    git("init", "--bare", str(origin))
    proj = root / nome
    git("clone", str(origin), str(proj))
    git("-C", str(proj), "config", "user.email", "t@example.com")
    git("-C", str(proj), "config", "user.name", "t")
    (proj / "README.md").write_text("hello\n")
    git("-C", str(proj), "add", "README.md")
    git("-C", str(proj), "commit", "-m", "init")
    git("-C", str(proj), "push", "origin", "HEAD")
    return origin, proj


def claimed(conn, **cols):
    tid = kb.create_task(conn, title="t", assignee="worker")
    if cols:
        sets = ", ".join(f"{k}=?" for k in cols)
        with kb.write_txn(conn):
            conn.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*cols.values(), tid))
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
    assert kb.claim_task(conn, tid, claimer="worker") is not None
    return tid


def eventos(conn, tid):
    return [r[0] for r in conn.execute(
        "SELECT kind FROM task_events WHERE task_id=? ORDER BY id", (tid,))]


def payload(conn, tid, kind):
    row = conn.execute(
        "SELECT payload FROM task_events WHERE task_id=? AND kind=? ORDER BY id DESC LIMIT 1",
        (tid, kind)).fetchone()
    return json.loads(row[0]) if row and row[0] else {}


print("=" * 74)
print("W3 — remoto forjado pelo worker: a forja ficou AUDITAVEL?")
print("=" * 74)
with kbc.connect() as conn:
    d = RAIZ / "w3"; d.mkdir()
    origin, proj = origem_e_clone(d)
    tid = claimed(conn)
    wt = proj / ".worktrees" / tid
    kbw._ensure_git_worktree(proj, wt, f"wt/{tid}")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET workspace_kind='worktree', workspace_path=? WHERE id=?",
                     (str(wt), tid))
    (wt / "f.txt").write_text("x")
    git("-C", str(wt), "add", "f.txt")
    git("-C", str(wt), "commit", "-m", "local")
    head = git("-C", str(wt), "rev-parse", "HEAD").strip()
    fake = d / "remoto-de-mentira.git"
    git("init", "--bare", str(fake))
    git("-C", str(wt), "remote", "set-url", "origin", str(fake))
    git("-C", str(wt), "push", "origin", "HEAD")
    assert head not in git("-C", str(proj), "ls-remote", str(origin))

    kb.complete_task(conn, tid, summary="empurrei (para um remoto que eu inventei)")
    print(f"  status do card      : {kb.get_task(conn, tid).status}")
    repos = payload(conn, tid, "completion_evidence_verified").get("repos", [])
    urls = [r.get("remote_url") for r in repos]
    print(f"  URL gravada no evento: {urls}")
    print(f"  aponta para a forja? : {str(fake) in urls}")
    print(f"  origin REAL era      : {origin}")
    print("  -> o card fecha (limitacao declarada), mas a troca de remoto")
    print("     agora esta GRAVADA. Antes nao havia registro nenhum.")

print()
print("=" * 74)
print("W4 — worktree com arquivo NAO commitado: o trabalho SOBREVIVEU?")
print("=" * 74)
with kbc.connect() as conn:
    d = RAIZ / "w4"; d.mkdir()
    origin, proj = origem_e_clone(d)
    tid = claimed(conn)
    wt = proj / ".worktrees" / tid
    kbw._ensure_git_worktree(proj, wt, f"wt/{tid}")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET workspace_kind='worktree', workspace_path=? WHERE id=?",
                     (str(wt), tid))
    git("-C", str(wt), "push", "origin", f"HEAD:refs/heads/wt-{tid}")
    entregavel = wt / "trabalho-de-8-horas.py"
    entregavel.write_text("# 8 horas, nunca commitado\n")

    kb.complete_task(conn, tid, summary="Entreguei. 53 arquivos novos.")
    print(f"  status do card          : {kb.get_task(conn, tid).status}")
    print(f"  arquivo ainda no disco? : {entregavel.exists()}")
    print(f"  caminho                 : {entregavel}")
    print("  -> a PERDA e o defeito; fechar o card nao e. O card proibe")
    print("     explicitamente transformar isso numa recusa.")

print()
print("=" * 74)
print("W1 — worktree EXTERNO, scratch nao-git, metadata omitida")
print("=" * 74)
with kbc.connect() as conn:
    d = RAIZ / "w1"; d.mkdir()
    origin, proj = origem_e_clone(d)
    scratch = d / "scratch-ws"
    scratch.mkdir()
    tid = claimed(conn, workspace_kind="scratch", workspace_path=str(scratch))
    externo = proj / ".worktrees" / f"ext-{tid}"
    kbw._ensure_git_worktree(proj, externo, f"wt/ext-{tid}")
    (externo / "f.txt").write_text("x")
    git("-C", str(externo), "add", "f.txt")
    git("-C", str(externo), "commit", "-m", "local nao empurrado")

    kb.complete_task(conn, tid, summary="Implementei, testei, tudo passou.")
    print(f"  status do card : {kb.get_task(conn, tid).status}")
    print(f"  workspace      : {scratch}  (nao-git)")
    print(f"  trabalho em    : {externo}  (nao empurrado)")
    print("  -> NAO HA LIGACAO objetiva entre o card e esse repo: o scratch nao")
    print("     e git, a metadata cala, e o board nao tem default_workdir.")
    print("     RESIDUO REAL, nao resolvido. Ver comentario no card.")
print()
