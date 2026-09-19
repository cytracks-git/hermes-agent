"""Tests for the Kanban evidence gate on task completion (C1-C9).

Verifies that complete_task refuses closure when:
  - There are unpushed commits in the workspace (C1) -> UnpushedWorkError,
    remains in-flight, audit event completion_blocked_unpushed.
  - Same task after `git push` succeeds (C2).
  - Read-only task with clean workspace completes (C3).
  - Claimed commit SHA in typed metadata cannot be resolved (C4) -> UnknownShaError.
  - Real HEAD SHA in metadata["commit"] completes (C5).
  - Non-git workspace read-only completes (C6).
  - force=True bypasses evidence gate (C7).
  - Unknown SHA in prose summary does not block, emits advisory event (C8).
  - kanban_tools._handle_complete catches UnpushedWorkError and UnknownShaError (C9).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_workspace as kbw


def _git(*args: str, cwd: str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert result.returncode == 0, f"git {' '.join(args)} failed: {result.stderr}"
    return result.stdout


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


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
    """A project repo with a remote whose history is fully pushed."""
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


def _make_worktree(repo: Path, task_id: str, branch: str | None = None) -> Path:
    target = repo / ".worktrees" / task_id
    kbw._ensure_git_worktree(repo, target, branch or f"wt/{task_id}")
    return target


def _worktree_task(conn, repo: Path, title: str = "wt-task") -> tuple[str, Path]:
    tid = kb.create_task(conn, title=title, assignee="worker")
    wt = _make_worktree(repo, tid)
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET workspace_kind='worktree', workspace_path=?, "
            "branch_name=? WHERE id=?",
            (str(wt), f"wt/{tid}", tid),
        )
    return tid, wt


# ---------------------------------------------------------------------------
# Test Cases C1 - C9
# ---------------------------------------------------------------------------


def test_c1_c2_unpushed_commit_blocked_then_succeeds_after_push(kanban_home: Path, repo: Path) -> None:
    """C1: commit local nao empurrado -> UnpushedWorkError; status running; audit event.
    C2: o MESMO card, depois de `git push`, complete_task retorna True e status done."""
    with kbc.connect_closing() as conn:
        tid, wt = _worktree_task(conn, repo)
        with kb.write_txn(conn):
            conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
        assert kb.claim_task(conn, tid, claimer="worker") is not None

        # Create a local commit not pushed to origin
        (wt / "file.txt").write_text("hello", encoding="utf-8")
        _git("-C", str(wt), "add", "file.txt")
        _git("-C", str(wt), "commit", "-m", "local commit")
        local_head = _git("-C", str(wt), "rev-parse", "HEAD").strip()

        # C1: complete_task must raise UnpushedWorkError
        with pytest.raises(kb.UnpushedWorkError) as exc_info:
            kb.complete_task(conn, tid, summary="attempt completion")

        err = exc_info.value
        assert err.unpushed_count == 1
        assert err.head_sha == local_head
        assert err.completing_task_id == tid
        assert "git push" in str(err)

        # Task status must remain 'running'
        task = kb.get_task(conn, tid)
        assert task.status == "running"

        # Event completion_blocked_unpushed must exist
        events = kb.list_events(conn, tid)
        unpushed_events = [e for e in events if e.kind == "completion_blocked_unpushed"]
        assert len(unpushed_events) == 1
        payload = unpushed_events[0].payload
        assert payload.get("unpushed_commits") == 1
        assert payload.get("head_sha") == local_head

        # C2: same card after git push -> complete_task succeeds
        _git("-C", str(wt), "push", "origin", "HEAD")
        assert kb.complete_task(conn, tid, summary="pushed and done") is True

        task = kb.get_task(conn, tid)
        assert task.status == "done"


def test_c3_clean_workspace_no_commits_read_only_completes(kanban_home: Path, repo: Path) -> None:
    """C3: workspace git limpo, so o commit-base ja empurrado, summary de leitura, sem metadata -> fecha."""
    with kbc.connect_closing() as conn:
        tid, wt = _worktree_task(conn, repo)
        with kb.write_txn(conn):
            conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
        assert kb.claim_task(conn, tid, claimer="worker") is not None

        # Clean workspace, no new commits, read-only summary, no metadata
        assert kb.complete_task(conn, tid, summary="read only task, no changes") is True
        task = kb.get_task(conn, tid)
        assert task.status == "done"


def test_c4_c5_invented_sha_in_metadata_blocked_real_sha_succeeds(kanban_home: Path, repo: Path) -> None:
    """C4: metadata com SHA inventado -> UnknownShaError, status running, evento completion_blocked_unknown_sha.
    C5: mutante de C4: SHA real do HEAD empurrado em metadata['commit'] -> fecha."""
    with kbc.connect_closing() as conn:
        tid, wt = _worktree_task(conn, repo)
        with kb.write_txn(conn):
            conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
        assert kb.claim_task(conn, tid, claimer="worker") is not None

        # C4: Invented SHA in typed metadata key
        invented_sha = "26a863b3cc929999999999999999999999999999"
        with pytest.raises(kb.UnknownShaError) as exc_info:
            kb.complete_task(conn, tid, summary="done", metadata={"commit": invented_sha})

        err = exc_info.value
        assert invented_sha in err.unknown_shas
        assert err.completing_task_id == tid

        task = kb.get_task(conn, tid)
        assert task.status == "running"

        events = kb.list_events(conn, tid)
        unknown_events = [e for e in events if e.kind == "completion_blocked_unknown_sha"]
        assert len(unknown_events) == 1
        assert invented_sha in unknown_events[0].payload.get("unknown_shas", [])

        # Short fake SHA also rejected (e.g. 12 hex)
        with pytest.raises(kb.UnknownShaError):
            kb.complete_task(conn, tid, summary="done", metadata={"sha": "26a863b3cc92"})

        # C5: Real SHA of HEAD in metadata["commit"] -> succeeds
        head_sha = _git("-C", str(wt), "rev-parse", "HEAD").strip()
        assert kb.complete_task(conn, tid, summary="done with real sha", metadata={"commit": head_sha}) is True

        task = kb.get_task(conn, tid)
        assert task.status == "done"


def test_c6_non_git_workspace_read_only_completes(kanban_home: Path, tmp_path: Path) -> None:
    """C6: workspace SEM git (dir comum, sem .git) + summary de leitura -> fecha."""
    plain_dir = tmp_path / "plain_dir"
    plain_dir.mkdir()
    with kbc.connect_closing() as conn:
        tid = kb.create_task(conn, title="read-docs", assignee="worker")
        with kb.write_txn(conn):
            conn.execute(
                "UPDATE tasks SET status='ready', workspace_kind='dir', workspace_path=? WHERE id=?",
                (str(plain_dir), tid),
            )
        assert kb.claim_task(conn, tid, claimer="worker") is not None

        assert kb.complete_task(conn, tid, summary="read plain docs") is True
        task = kb.get_task(conn, tid)
        assert task.status == "done"


def test_c7_force_bypasses_evidence_gate(kanban_home: Path, repo: Path) -> None:
    """C7: force=True com commit nao empurrado -> fecha (override do operador)."""
    with kbc.connect_closing() as conn:
        tid, wt = _worktree_task(conn, repo)
        with kb.write_txn(conn):
            conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
        assert kb.claim_task(conn, tid, claimer="worker") is not None

        # Make an unpushed commit
        (wt / "unpushed.txt").write_text("data", encoding="utf-8")
        _git("-C", str(wt), "add", "unpushed.txt")
        _git("-C", str(wt), "commit", "-m", "unpushed commit")

        # force=True must bypass evidence gate
        assert kb.complete_task(conn, tid, summary="operator override", force=True) is True
        task = kb.get_task(conn, tid)
        assert task.status == "done"


def test_c8_unknown_sha_in_prose_summary_does_not_block(kanban_home: Path, repo: Path) -> None:
    """C8: SHA de 40 hex no SUMMARY (nao na metadata) de um commit que nao existe -> FECHA.
    Emite evento advisory suspected_unknown_sha_in_prose sem bloquear."""
    with kbc.connect_closing() as conn:
        tid, wt = _worktree_task(conn, repo)
        with kb.write_txn(conn):
            conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
        assert kb.claim_task(conn, tid, claimer="worker") is not None

        prose_sha = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        summary = f"Referenced external commit {prose_sha} for inspection"
        assert kb.complete_task(conn, tid, summary=summary) is True
        task = kb.get_task(conn, tid)
        assert task.status == "done"

        events = kb.list_events(conn, tid)
        advisory_events = [e for e in events if e.kind == "suspected_unknown_sha_in_prose"]
        assert len(advisory_events) == 1
        assert prose_sha in advisory_events[0].payload.get("unknown_shas", [])


def test_c9_tool_handler_catches_unpushed_and_unknown_sha(monkeypatch, tmp_path: Path, repo: Path) -> None:
    """C9: o handler tools/kanban_tools.py _handle_complete captura UnpushedWorkError
    e UnknownShaError e devolve tool_error contendo 'still in-flight' e 'git push'."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_PROFILE", "test-worker")
    monkeypatch.delenv("HERMES_SESSION_ID", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    with kbc.connect_closing() as conn:
        tid, wt = _worktree_task(conn, repo)
        with kb.write_txn(conn):
            conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
        run = kb.claim_task(conn, tid, claimer="test-worker")
        assert run is not None

    monkeypatch.setenv("HERMES_KANBAN_TASK", tid)
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", str(run.id))

    from tools import kanban_tools as kt

    # 1. Unpushed commit scenario
    (wt / "work.txt").write_text("some work", encoding="utf-8")
    _git("-C", str(wt), "add", "work.txt")
    _git("-C", str(wt), "commit", "-m", "add work")

    out = kt._handle_complete({"summary": "trying to complete"})
    d = json.loads(out)
    assert d.get("error")
    err_msg = d["error"]
    assert "in-flight" in err_msg
    assert "git push" in err_msg

    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).status == "running"

    # Push commit so unpushed error clears
    _git("-C", str(wt), "push", "origin", "HEAD")

    # 2. Unknown SHA scenario
    out2 = kt._handle_complete({
        "summary": "trying to complete with bad sha",
        "metadata": {"commit": "1111222233334444555566667777888899990000"},
    })
    d2 = json.loads(out2)
    assert d2.get("error")
    err_msg2 = d2["error"]
    assert "in-flight" in err_msg2

    with kbc.connect_closing() as conn:
        assert kb.get_task(conn, tid).status == "running"


def test_no_remotes_skips_unpushed_gate(kanban_home: Path, tmp_path: Path) -> None:
    """Workspace with git repo but NO remotes configured must skip unpushed check."""
    local_repo = tmp_path / "local_repo"
    _git("init", str(local_repo))
    _git("-C", str(local_repo), "config", "user.email", "t@example.com")
    _git("-C", str(local_repo), "config", "user.name", "t")
    (local_repo / "file.txt").write_text("initial", encoding="utf-8")
    _git("-C", str(local_repo), "add", "file.txt")
    _git("-C", str(local_repo), "commit", "-m", "initial commit")

    with kbc.connect_closing() as conn:
        tid = kb.create_task(conn, title="no-remotes", assignee="worker")
        with kb.write_txn(conn):
            conn.execute(
                "UPDATE tasks SET status='ready', workspace_kind='dir', workspace_path=? WHERE id=?",
                (str(local_repo), tid),
            )
        assert kb.claim_task(conn, tid, claimer="worker") is not None

        # Should complete because there are no remotes to compare against
        assert kb.complete_task(conn, tid, summary="completed without remotes") is True
        task = kb.get_task(conn, tid)
        assert task.status == "done"
