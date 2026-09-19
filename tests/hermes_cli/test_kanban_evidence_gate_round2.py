"""Round 2 do gate de evidencia: os dois BLOQUEANTES da rodada 1, reproduzidos.

A rodada 1 usava refs LOCAIS como autoridade (`for-each-ref refs/remotes` +
`rev-list HEAD --not --remotes`) e engolia falha de sonda com `except: pass`.
O revisor derrubou os dois. Estes testes sao o RED dessa reprova:

  X2  `git update-ref refs/remotes/origin/forjado HEAD` SEM push -> tem de RECUSAR.
      A rodada 1 ACEITAVA: refs/remotes e escrivel pelo worker.

  X1  workspace scratch nao-git + commit nao empurrado num worktree externo
      declarado em metadata -> tem de RECUSAR.
      A rodada 1 ACEITAVA: so olhava workspace_path.

  X3  sonda impossivel de medir (remoto inalcancavel) -> tem de RECUSAR
      (UnmeasuredEvidenceError). A rodada 1 tratava como "limpo".

CONTROLE POSITIVO em cada caso: o mesmo cenario com o trabalho de fato
empurrado tem de FECHAR. Um gate que recusa todo mundo nao e gate.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_workspace as kbw


def _git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    if check:
        assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout


@pytest.fixture
def kanban_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    origin = tmp_path / "origin.git"
    _git("init", "--bare", str(origin))
    project = tmp_path / "project"
    _git("clone", str(origin), str(project))
    _git("-C", str(project), "config", "user.email", "t@example.com")
    _git("-C", str(project), "config", "user.name", "t")
    (project / "README.md").write_text("hello\n", encoding="utf-8")
    _git("-C", str(project), "add", "README.md")
    _git("-C", str(project), "commit", "-m", "init")
    _git("-C", str(project), "push", "origin", "HEAD")
    return project


def _claimed_task(conn, **cols) -> str:
    tid = kb.create_task(conn, title="t", assignee="worker")
    if cols:
        sets = ", ".join(f"{k}=?" for k in cols)
        with kb.write_txn(conn):
            conn.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*cols.values(), tid))
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
    assert kb.claim_task(conn, tid, claimer="worker") is not None
    return tid


def _worktree(conn, repo: Path, tid: str) -> Path:
    target = repo / ".worktrees" / tid
    kbw._ensure_git_worktree(repo, target, f"wt/{tid}")
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET workspace_kind='worktree', workspace_path=?, branch_name=? WHERE id=?",
            (str(target), f"wt/{tid}", tid))
    return target


def _commit(wt: Path, name: str = "f.txt") -> str:
    (wt / name).write_text("x", encoding="utf-8")
    _git("-C", str(wt), "add", name)
    _git("-C", str(wt), "commit", "-m", "local work")
    return _git("-C", str(wt), "rev-parse", "HEAD").strip()


# --------------------------------------------------------------------------
# X2 — BLOQUEANTE 1: refs/remotes forjada nao pode autorizar o fechamento
# --------------------------------------------------------------------------

def test_x2_forged_remote_ref_without_push_is_refused(kanban_home: Path, repo: Path) -> None:
    """O worker escreve refs/remotes/origin/* sem push. A rodada 1 aceitava.

    A autoridade tem de ser o anuncio do remoto (ls-remote), que o worker
    nao controla.
    """
    with kbc.connect_closing() as conn:
        tid = _claimed_task(conn)
        wt = _worktree(conn, repo, tid)
        head = _commit(wt)

        # A FORJA: ref local em refs/remotes, nenhum push.
        _git("-C", str(wt), "update-ref", "refs/remotes/origin/forjado", head)

        # O remoto de verdade nao conhece esse sha.
        anunciado = _git("-C", str(wt), "ls-remote", "origin")
        assert head not in anunciado, "pre-condicao: o push nao aconteceu"

        with pytest.raises(kb.UnpushedWorkError):
            kb.complete_task(conn, tid, summary="forjei refs/remotes")

        assert kb.get_task(conn, tid).status == "running"


def test_x2b_control_same_card_after_real_push_completes(kanban_home: Path, repo: Path) -> None:
    """CONTROLE POSITIVO de X2: push de verdade fecha. O gate nao recusa todo mundo."""
    with kbc.connect_closing() as conn:
        tid = _claimed_task(conn)
        wt = _worktree(conn, repo, tid)
        _commit(wt)
        _git("-C", str(wt), "push", "origin", "HEAD")

        assert kb.complete_task(conn, tid, summary="empurrado de verdade") is True
        assert kb.get_task(conn, tid).status == "done"


# --------------------------------------------------------------------------
# X1 — BLOQUEANTE 2: workspace scratch nao-git com trabalho num worktree externo
# --------------------------------------------------------------------------

def test_x1_scratch_workspace_with_unpushed_external_worktree_is_refused(
    kanban_home: Path, repo: Path, tmp_path: Path,
) -> None:
    """73 de 81 cards do board real sao scratch (nao-git). O trabalho vive fora.

    A rodada 1 so olhava workspace_path: card scratch fechava com commit local
    perdido num worktree externo. Declarar o worktree em metadata tem de ser
    MAIS medido, nao menos.
    """
    with kbc.connect_closing() as conn:
        scratch = tmp_path / "scratch-ws"
        scratch.mkdir()
        tid = _claimed_task(conn, workspace_kind="scratch", workspace_path=str(scratch))

        # O trabalho real acontece num worktree FORA do workspace do card.
        externo = repo / ".worktrees" / f"ext-{tid}"
        kbw._ensure_git_worktree(repo, externo, f"wt/ext-{tid}")
        head = _commit(externo)

        with pytest.raises(kb.UnpushedWorkError):
            kb.complete_task(
                conn, tid, summary="trabalhei no worktree externo",
                metadata={"worktree": str(externo), "commit": head},
            )

        assert kb.get_task(conn, tid).status == "running"


def test_x1b_control_declared_external_worktree_pushed_completes(
    kanban_home: Path, repo: Path, tmp_path: Path,
) -> None:
    """CONTROLE POSITIVO de X1: mesmo card, worktree externo empurrado -> fecha."""
    with kbc.connect_closing() as conn:
        scratch = tmp_path / "scratch-ws"
        scratch.mkdir()
        tid = _claimed_task(conn, workspace_kind="scratch", workspace_path=str(scratch))

        externo = repo / ".worktrees" / f"ext-{tid}"
        kbw._ensure_git_worktree(repo, externo, f"wt/ext-{tid}")
        head = _commit(externo)
        _git("-C", str(externo), "push", "origin", "HEAD")

        assert kb.complete_task(
            conn, tid, summary="worktree externo empurrado",
            metadata={"worktree": str(externo), "commit": head},
        ) is True
        assert kb.get_task(conn, tid).status == "done"


def test_x1c_pure_reading_scratch_task_still_completes(kanban_home: Path, tmp_path: Path) -> None:
    """CONTROLE POSITIVO do recorte: card de leitura pura nao vira paranoia.

    Workspace scratch medido como NAO-git, nenhum caminho git declarado,
    nenhum SHA tipado -> fecha. Este e o predicado afirmativo.
    """
    with kbc.connect_closing() as conn:
        scratch = tmp_path / "leitura"
        scratch.mkdir()
        (scratch / "notas.md").write_text("levantamento\n", encoding="utf-8")
        tid = _claimed_task(conn, workspace_kind="scratch", workspace_path=str(scratch))

        assert kb.complete_task(conn, tid, summary="li e medi, nada a commitar") is True
        assert kb.get_task(conn, tid).status == "done"


# --------------------------------------------------------------------------
# X3 — BLOQUEANTE 2 (segunda metade): nao-medido != limpo
# --------------------------------------------------------------------------

def test_x3_unreachable_remote_refuses_instead_of_closing(
    kanban_home: Path, repo: Path,
) -> None:
    """Sonda que nao consegue medir tem de RECUSAR, nunca fechar.

    Aponta o remoto para um caminho inexistente: ls-remote falha. A rodada 1
    caia no `except: pass` e fechava o card.
    """
    with kbc.connect_closing() as conn:
        tid = _claimed_task(conn)
        wt = _worktree(conn, repo, tid)
        _commit(wt)
        _git("-C", str(wt), "remote", "set-url", "origin", "/nao/existe/origin.git")

        with pytest.raises(kb.UnmeasuredEvidenceError):
            kb.complete_task(conn, tid, summary="remoto fora do ar")

        assert kb.get_task(conn, tid).status == "running"


def test_x3b_control_no_remote_configured_is_also_unmeasured(
    kanban_home: Path, repo: Path,
) -> None:
    """Repo git com commit local e NENHUM remoto: nao da para provar push.

    A rodada 1 tinha um teste afirmando que isso e sucesso
    (`test_no_remotes_skips_unpushed_gate`). E o falso-verde na forma pura.
    """
    with kbc.connect_closing() as conn:
        tid = _claimed_task(conn)
        wt = _worktree(conn, repo, tid)
        _commit(wt)
        _git("-C", str(wt), "remote", "remove", "origin")

        with pytest.raises(kb.UnmeasuredEvidenceError):
            kb.complete_task(conn, tid, summary="sem remoto nenhum")

        assert kb.get_task(conn, tid).status == "running"
