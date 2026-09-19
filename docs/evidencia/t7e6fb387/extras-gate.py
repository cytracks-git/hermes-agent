#!/usr/bin/env python3
"""Controles extras que o Writer nao cobriu: SHA maiusculo, origin-sem-fetch,
rev-list que falha (fail-open). Roda contra o codigo NOVO.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

WT = Path("/Users/farantes/atlas/wt/gate-evidencia")
sys.path.insert(0, str(WT))
os.chdir(WT)

# ISOLAMENTO ANTES DE QUALQUER IMPORT DO KANBAN. Este script setava apenas
# HERMES_HOME, e `HERMES_KANBAN_DB` (injetado em todo worker) VENCE: os cards de
# fixture iam para o board de PRODUCAO. Medido em causa-colateral-board.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolar_board import afirmar_isolado, isolar_board  # noqa: E402

_RAIZ_ISOLADA = isolar_board("extras-gate-")

from hermes_cli import kanban_db as kb          # noqa: E402
from hermes_cli import kanban_db_connect as kbc  # noqa: E402
from hermes_cli import kanban_db_workspace as kbw  # noqa: E402


def git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


def make_home(tmp: Path):
    """O isolamento ja foi feito por isolar_board(); aqui so se reconfirma.

    Reconferir a cada fixture e barato e impede que uma edicao futura mova o
    import para antes do isolamento sem ninguem perceber.
    """
    afirmar_isolado()
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return Path(os.environ["HERMES_HOME"])


def make_repo(tmp: Path) -> Path:
    origin = tmp / "origin.git"
    git("init", "--bare", str(origin))
    project = tmp / "project"
    git("clone", str(origin), str(project))
    git("-C", str(project), "config", "user.email", "t@example.com")
    git("-C", str(project), "config", "user.name", "t")
    (project / "README.md").write_text("hello\n")
    git("-C", str(project), "add", "README.md")
    git("-C", str(project), "commit", "-m", "init")
    git("-C", str(project), "push", "origin", "HEAD")
    return project


def worktree_task(conn, repo, title="t"):
    tid = kb.create_task(conn, title=title, assignee="worker")
    wt = repo / ".worktrees" / tid
    kbw._ensure_git_worktree(repo, wt, f"wt/{tid}")
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET workspace_kind='worktree', workspace_path=?, branch_name=? WHERE id=?",
            (str(wt), f"wt/{tid}", tid),
        )
    return tid, wt


def claim(conn, tid):
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
    assert kb.claim_task(conn, tid, claimer="worker") is not None


def report(nome, esperado, obtido, detalhe=""):
    ok = esperado == obtido
    print(f"{'OK  ' if ok else 'FALHA'} {nome}")
    print(f"       esperado={esperado} obtido={obtido} {detalhe}")
    return ok


def main():
    n_ok = 0
    n = 0

    # X1: SHA maiusculo do HEAD real
    tmp = Path(tempfile.mkdtemp(prefix="x1-"))
    make_home(tmp)
    repo = make_repo(tmp)
    with kbc.connect_closing() as conn:
        tid, wt = worktree_task(conn, repo)
        claim(conn, tid)
        head = git("-C", str(wt), "rev-parse", "HEAD").strip()
        upper = head.upper()
        try:
            ok = kb.complete_task(conn, tid, summary="upper sha", metadata={"commit": upper})
            status = kb.get_task(conn, tid).status
            n += 1
            n_ok += report("X1 SHA maiusculo do HEAD real", "ACEITOU", "ACEITOU" if ok and status == "done" else f"ok={ok} status={status}", f"sha={upper[:12]}")
        except Exception as e:
            n += 1
            n_ok += report("X1 SHA maiusculo do HEAD real", "ACEITOU", "RECUSOU", type(e).__name__)

    # X2: origin configurado, refs/remotes vazio (nunca fez fetch) + commit local
    tmp = Path(tempfile.mkdtemp(prefix="x2-"))
    make_home(tmp)
    origin = tmp / "origin.git"
    git("init", "--bare", str(origin))
    project = tmp / "project"
    git("clone", str(origin), str(project))
    git("-C", str(project), "config", "user.email", "t@example.com")
    git("-C", str(project), "config", "user.name", "t")
    (project / "README.md").write_text("hello\n")
    git("-C", str(project), "add", "README.md")
    git("-C", str(project), "commit", "-m", "init")
    git("-C", str(project), "push", "origin", "HEAD")
    # apaga refs/remotes para simular clone que nunca fez fetch
    git("-C", str(project), "remote", "remove", "origin")
    git("-C", str(project), "remote", "add", "origin", str(origin))
    # confirmar: origin existe, refs/remotes vazio
    remotes = git("-C", str(project), "for-each-ref", "--format=%(refname)", "refs/remotes")
    print(f"X2 refs/remotes={remotes!r} origin.url={git('-C', str(project), 'remote', 'get-url', 'origin').strip()}")
    with kbc.connect_closing() as conn:
        tid = kb.create_task(conn, title="nofetch", assignee="worker")
        with kb.write_txn(conn):
            conn.execute(
                "UPDATE tasks SET status='ready', workspace_kind='dir', workspace_path=? WHERE id=?",
                (str(project), tid),
            )
        assert kb.claim_task(conn, tid, claimer="worker") is not None
        (project / "x.txt").write_text("x")
        git("-C", str(project), "add", "x.txt")
        git("-C", str(project), "commit", "-m", "local")
        try:
            ok = kb.complete_task(conn, tid, summary="unpushed, never fetched")
            status = kb.get_task(conn, tid).status
            n += 1
            # O recorte do card: sem refs/remotes, PULAR o gate. Entao ACEITA.
            # Relatar, nao exigir recusa — e o recorte. Mas e um furo.
            n_ok += report(
                "X2 origin existe, refs/remotes vazio, commit local",
                "ACEITOU (recorte: pular sem remotes)",
                "ACEITOU" if ok and status == "done" else f"ok={ok} status={status}",
            )
        except Exception as e:
            n += 1
            n_ok += report(
                "X2 origin existe, refs/remotes vazio, commit local",
                "ACEITOU (recorte: pular sem remotes)",
                "RECUSOU",
                type(e).__name__,
            )

    # X3: metadata["commits"] lista com SHA inventado
    tmp = Path(tempfile.mkdtemp(prefix="x3-"))
    make_home(tmp)
    repo = make_repo(tmp)
    with kbc.connect_closing() as conn:
        tid, wt = worktree_task(conn, repo)
        claim(conn, tid)
        fake = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        try:
            ok = kb.complete_task(conn, tid, summary="lista", metadata={"commits": [fake]})
            status = kb.get_task(conn, tid).status
            n += 1
            n_ok += report("X3 metadata.commits lista SHA inventado", "RECUSOU", "ACEITOU" if ok else "RECUSOU sem raise", f"status={status}")
        except kb.UnknownShaError as e:
            n += 1
            n_ok += report("X3 metadata.commits lista SHA inventado", "RECUSOU", "RECUSOU", f"unknown={e.unknown_shas}")
        except Exception as e:
            n += 1
            n_ok += report("X3 metadata.commits lista SHA inventado", "RECUSOU", type(e).__name__)

    print(f"conformes extras: {n_ok}/{n}")
    return 0 if n_ok == n else 1


if __name__ == "__main__":
    sys.exit(main())
