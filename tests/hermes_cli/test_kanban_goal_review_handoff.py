"""Goal-mode request-review is not the complete judge.

A card whose body mandates independent review used to refuse the handoff
that starts that review (circular). Complete still requires the goal so
the author cannot close. Coordinator CLI (no worker run) uses the same
review skip — it must not inherit the writer's goal-loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from hermes_cli import kanban as kc
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc

_CIRCULAR_CONTINUE = (
    "continue",
    "mandated independent review has not returned a verdict yet",
    False,
    None,
    False,
)

_BODY = (
    "Implement the fix and obtain independent review from profile revisor. "
    "Aceite: parecer do revisor; o autor nao fecha."
)
_EVIDENCE = "commit 4b4ae2fef5 tests green"


def _home(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_PROFILE", "builder")
    monkeypatch.delenv("HERMES_DELEGATED_CHILD_CONTEXT", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_RUN_ID", raising=False)
    (home / "profiles" / "revisor").mkdir(parents=True)
    (home / "profiles" / "revisor" / "config.yaml").write_text("{}\n")
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


def _create_goal_card(conn, *, assignee="builder"):
    return kb.create_task(
        conn,
        title="Fix circular goal-judge on request-review",
        assignee=assignee,
        body=_BODY,
        goal_mode=True,
    )


def test_same_card_complete_refused_request_review_passes(
    monkeypatch, tmp_path: Path,
) -> None:
    """RED: request-review lands in review/revisor. GREEN: complete stays refused."""
    _home(monkeypatch, tmp_path)
    with kbc.connect() as conn:
        tid = _create_goal_card(conn)
        claimed = kb.claim_task(conn, tid, claimer="builder:1")
        assert claimed is not None
    monkeypatch.setenv("HERMES_KANBAN_TASK", tid)
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", str(claimed.current_run_id))

    from tools import kanban_tools as tools

    monkeypatch.setattr(tools, "_goal_judge_available", lambda: True)
    monkeypatch.setattr(tools, "judge_goal", lambda *a, **k: _CIRCULAR_CONTINUE)

    refused = json.loads(tools._handle_complete({"summary": _EVIDENCE}))
    assert "error" in refused
    assert "rejected by judge" in refused["error"]
    assert "independent review" in refused["error"]
    with kbc.connect() as conn:
        still_running = kb.get_task(conn, tid)
        assert still_running is not None
        assert still_running.status == "running"

    accepted = json.loads(tools._handle_request_review({
        "summary": _EVIDENCE,
        "reviewer": "revisor",
        "metadata": {"commit": "4b4ae2fef5", "tests_run": 1},
    }))
    assert accepted.get("ok") is True, accepted
    with kbc.connect() as conn:
        task = kb.get_task(conn, tid)
        assert task is not None
        assert task.status == "review"
        assert task.assignee == "revisor"


def test_cli_coordinator_request_review_without_worker_run(
    monkeypatch, tmp_path: Path,
) -> None:
    """Coordinator CLI has no HERMES_KANBAN_RUN_ID and must still hand off."""
    _home(monkeypatch, tmp_path)
    with kbc.connect() as conn:
        tid = _create_goal_card(conn)

    import agent.auxiliary_client as auxiliary_client
    from hermes_cli import goals

    monkeypatch.setattr(
        auxiliary_client,
        "get_text_auxiliary_client",
        lambda purpose: (object(), "judge-model"),
    )
    monkeypatch.setattr(goals, "judge_goal", lambda *a, **k: _CIRCULAR_CONTINUE)

    output = kc.run_slash(
        f"request-review {tid} --summary '{_EVIDENCE}' --reviewer revisor"
    )
    assert "rejected by judge" not in output
    assert "Requested review" in output
    with kbc.connect() as conn:
        task = kb.get_task(conn, tid)
        assert task is not None
        assert task.status == "review"
        assert task.assignee == "revisor"


def test_cli_complete_still_judged_on_circular_body(
    monkeypatch, tmp_path: Path,
) -> None:
    """Sabotaging complete (no reviewer verdict) must still accuse."""
    _home(monkeypatch, tmp_path)
    with kbc.connect() as conn:
        tid = _create_goal_card(conn)
        claimed = kb.claim_task(conn, tid, claimer="builder:1")
        assert claimed is not None
    monkeypatch.setenv("HERMES_KANBAN_TASK", tid)
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", str(claimed.current_run_id))

    import agent.auxiliary_client as auxiliary_client
    from hermes_cli import goals

    monkeypatch.setattr(
        auxiliary_client,
        "get_text_auxiliary_client",
        lambda purpose: (object(), "judge-model"),
    )
    monkeypatch.setattr(goals, "judge_goal", lambda *a, **k: _CIRCULAR_CONTINUE)

    output = kc.run_slash(f"complete {tid} --summary '{_EVIDENCE}'")
    assert "rejected by judge" in output
    with kbc.connect() as conn:
        still_running = kb.get_task(conn, tid)
        assert still_running is not None
        assert still_running.status == "running"
