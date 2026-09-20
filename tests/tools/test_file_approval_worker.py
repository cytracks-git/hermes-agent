"""Prova de integração isolada: ferramenta real, SQLite e processos separados.

As decisões abaixo pertencem só ao banco temporário da fixture. Nenhuma superfície
humana viva nem arquivo de instruções do host participa desta prova.
"""
import json
import multiprocessing
import os
import queue
import sqlite3
import time
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_approvals as journal
from hermes_cli.kanban_db_connect import connect
from hermes_cli.kanban_approval_lifecycle import record_human_decision, reconcile_approval_orphans


def _worker(db, home, workspace, task, run, claim, mode, result_queue):
    os.environ.update(HERMES_HOME=home, HERMES_KANBAN_DB=db, HERMES_KANBAN_TASK=task,
                      HERMES_KANBAN_RUN_ID=str(run), HERMES_KANBAN_CLAIM_LOCK=claim,
                      TERMINAL_ENV="local", TERMINAL_CWD=workspace)
    os.environ.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
    from tools.approval_context import set_current_session_key
    from hermes_cli.kanban_db_dispatch import _set_worker_pid
    from tools import file_tools as ft
    set_current_session_key("fixture-session")
    os.chdir(workspace)
    conn = connect(Path(db))
    _set_worker_pid(conn, task, os.getpid())
    conn.close()
    path = str(Path(workspace) / "AGENTS.md")
    try:
        if mode == "write":
            ft.read_file_tool(path, task_id="fixture")
            answer = ft._handle_write_file({"path": path, "content": "approved\n"}, task_id="fixture")
        else:
            other = str(Path(workspace) / "other.txt")
            patch = (f"*** Begin Patch\n*** Update File: {path}\n@@\n-old\n+approved\n"
                     f"*** Update File: {other}\n@@\n-old\n+approved\n*** End Patch")
            answer = ft._handle_patch({"mode": "patch", "patch": patch}, task_id="fixture")
        result_queue.put(json.loads(answer))
    except BaseException as exc:
        result_queue.put({"error": repr(exc)})


def _pending(conn, result_queue, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        requests = journal.list_requests(conn, states=[journal.PENDING])
        if requests:
            return requests[0]
        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            time.sleep(0.05)
        else:
            pytest.fail(f"Worker returned before pending request: {result}")
    pytest.fail("Worker did not persist its pending request")


@pytest.mark.parametrize("mode", ["write", "patch"])
@pytest.mark.parametrize("stimulus", ["approve", "deny", "preimage", "symlink", "unreadable", "cancel", "capacity_host", "capacity_profile"])
def test_real_worker_waits_and_writes_only_the_approved_preimage(tmp_path, mode, stimulus):
    if stimulus == "unreadable" and os.geteuid() == 0:
        pytest.skip("Permission control requires a non-root Docker user")
    home = tmp_path / "home"
    home.mkdir()
    if stimulus.startswith("capacity_"):
        setting = "max_in_progress" if stimulus == "capacity_host" else "max_in_progress_per_profile"
        (home / "config.yaml").write_text(f"kanban:\n  {setting}: 1\n")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    protected = workspace / "AGENTS.md"
    protected.write_text("old\n")
    other = workspace / "other.txt"
    other.write_text("old\n")
    db = kb.init_db(db_path=tmp_path / "board.db")
    conn = connect(db)
    tid = kb.create_task(conn, title="isolated approval", assignee="fixture",
                         workspace_kind="dir", workspace_path=str(workspace))
    kb.recompute_ready(conn)
    task = kb.claim_task(conn, tid)
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    worker = context.Process(target=_worker, args=(str(db), str(home), str(workspace), tid,
                             task.current_run_id, task.claim_lock, mode, result_queue))
    worker.start()
    try:
        request = _pending(conn, result_queue)
        paused = kb.get_task(conn, tid)
        assert paused.status == "waiting_approval" and paused.claim_lock is None
        assert protected.read_text() == "old\n" and other.read_text() == "old\n"
        kb.add_comment(conn, tid, author="fixture", body="approved")
        assert journal.get_request(conn, request.request_id).state == journal.PENDING
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            with kb.write_txn(conn):
                conn.execute("UPDATE approval_requests SET payload_json='{}' WHERE request_id=?", (request.request_id,))
        assert not record_human_decision(conn, request.request_id, expected_hash="0" * 64,
                                        decision=journal.GRANTED, decided_by="fixture-human", decision_surface="desktop")
        if stimulus == "preimage":
            protected.write_text("external\n")
        elif stimulus == "symlink":
            protected.unlink()
            protected.symlink_to(other)
        elif stimulus == "unreadable":
            protected.chmod(0)
        decision = {"deny": journal.DENIED, "cancel": journal.CANCELLED}.get(stimulus, journal.GRANTED)
        competitor = None
        if stimulus.startswith("capacity_"):
            competitor = kb.create_task(conn, title="capacity fixture", assignee="fixture")
            kb.recompute_ready(conn)
            assert kb.claim_task(conn, competitor)
        assert record_human_decision(conn, request.request_id, expected_hash=request.request_hash,
                                     decision=decision, decided_by="fixture-human", decision_surface="desktop")
        if competitor:
            with pytest.raises(queue.Empty):
                result_queue.get(timeout=2)
            assert journal.get_request(conn, request.request_id).state == journal.GRANTED
            assert kb.get_task(conn, tid).status == "waiting_approval"
            assert protected.read_bytes() == b"old\n"
            assert kb.reclaim_task(conn, competitor, reason="release fixture capacity")
        result = result_queue.get(timeout=20)
        worker.join(timeout=10)
        assert worker.exitcode == 0
        current = journal.get_request(conn, request.request_id)
        if stimulus == "unreadable":
            protected.chmod(0o600)
        if stimulus == "approve" or stimulus.startswith("capacity_"):
            assert not result.get("error"), result
            assert result["verified"]
            assert protected.read_bytes() == b"approved\n"
            if mode == "patch":
                assert other.read_bytes() == b"approved\n"
            assert current.state == journal.CONSUMED and current.applied_at is not None
            resumed = kb.get_task(conn, tid)
            assert resumed.status == "running" and resumed.claim_lock == task.claim_lock
            assert resumed.worker_pid == worker.pid
        else:
            assert result.get("error"), result
            assert current.applied_at is None
            assert kb.get_task(conn, tid).status == "blocked"
            assert other.read_bytes() == b"old\n"
            if stimulus == "preimage":
                assert protected.read_bytes() == b"external\n"
            else:
                assert protected.read_bytes() == b"old\n"
        assert not record_human_decision(conn, request.request_id, expected_hash=request.request_hash,
                                        decision=journal.GRANTED, decided_by="fixture-human", decision_surface="desktop")
        assert not journal.consume_grant(conn, request.request_id)
    finally:
        if stimulus == "unreadable":
            protected.chmod(0o600)
        # Só a fixture criada por este teste, nunca worker de produção.
        if worker.is_alive():
            worker.terminate()
            worker.join(timeout=10)
        conn.close()
        result_queue.close()


@pytest.mark.parametrize("state", [journal.PENDING, journal.GRANTED, journal.CONSUMED])
def test_dead_creator_is_recovered_without_replaying(tmp_path, state):
    from hermes_cli.kanban_db_dispatch import TERMINAL_WORKER_REAP_GRACE_SECONDS
    db = kb.init_db(db_path=tmp_path / "board.db")
    conn = connect(db)
    try:
        tid = kb.create_task(conn, title="orphan fixture", assignee="fixture")
        kb.recompute_ready(conn)
        task = kb.claim_task(conn, tid)
        with kb.write_txn(conn):
            request = journal.create_request(
                conn, task_id=tid, run_id=task.current_run_id, claim_lock=task.claim_lock,
                profile_home=str(tmp_path), session_key="fixture", workspace_path=str(tmp_path),
                created_by_pid=99999999, created_by_started_at="dead-fixture",
                payload={"targets": []}, now=int(time.time()) - TERMINAL_WORKER_REAP_GRACE_SECONDS - 1)
            if state != journal.PENDING:
                journal.decide_request(conn, request.request_id, decision=journal.GRANTED,
                                       decided_by="fixture", decision_surface="desktop", expected_hash=request.request_hash)
            if state == journal.CONSUMED:
                journal.consume_grant(conn, request.request_id)
            assert kb.pause_for_approval(conn, tid, request_id=request.request_id,
                                         request_hash=request.request_hash, expected_run_id=task.current_run_id)
        assert reconcile_approval_orphans(conn) == [tid]
        assert journal.get_request(conn, request.request_id).state == journal.ORPHANED
        assert kb.get_task(conn, tid).status == "blocked"
        assert reconcile_approval_orphans(conn) == []
    finally:
        conn.close()


def test_two_real_workers_cannot_both_apply_the_same_preimage(tmp_path):
    home, workspace = tmp_path / "home", tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    target = workspace / "AGENTS.md"
    target.write_text("old\n")
    db = kb.init_db(db_path=tmp_path / "concurrent.db")
    conn = connect(db)
    context = multiprocessing.get_context("spawn")
    results, workers = context.Queue(), []
    try:
        for _ in range(2):
            tid = kb.create_task(conn, title="concurrent fixture", assignee="fixture",
                                 workspace_kind="dir", workspace_path=str(workspace))
            kb.recompute_ready(conn)
            task = kb.claim_task(conn, tid)
            child = context.Process(target=_worker, args=(str(db), str(home), str(workspace), tid,
                                    task.current_run_id, task.claim_lock, "write", results))
            child.start()
            workers.append(child)
        deadline = time.monotonic() + 20
        while len(journal.list_requests(conn, states=[journal.PENDING])) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        requests = journal.list_requests(conn, states=[journal.PENDING])
        assert len(requests) == 2
        assert target.read_bytes() == b"old\n"
        for request in requests:
            assert record_human_decision(conn, request.request_id, expected_hash=request.request_hash,
                                        decision=journal.GRANTED, decided_by="fixture-human", decision_surface="desktop")
        answers = [results.get(timeout=20) for _ in workers]
        for child in workers:
            child.join(timeout=10)
            assert child.exitcode == 0
        assert sum(bool(answer.get("verified")) for answer in answers) == 1
        assert sum("preimage changed" in answer.get("error", "") for answer in answers) == 1
        assert sum(item.applied_at is not None for item in journal.list_requests(conn)) == 1
        assert target.read_bytes() == b"approved\n"
    finally:
        for child in workers:
            if child.is_alive():
                child.terminate()
                child.join(timeout=10)
        results.close()
        conn.close()


@pytest.mark.parametrize("identity", ["profile", "session", "run", "claim", "task"])
def test_foreign_identity_cannot_consume_the_original_workers_grant(tmp_path, monkeypatch, identity):
    from tools import file_tools as ft
    from tools import file_approval_worker as worker
    from tools.approval_context import get_current_session_key, set_current_session_key
    from tools.file_approval_payload import prepare_payload
    from hermes_cli.kanban_db_dispatch import _set_worker_pid

    home, workspace = tmp_path / "home", tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    target = workspace / "AGENTS.md"
    target.write_text("old\n")
    db = kb.init_db(db_path=tmp_path / "identity.db")
    conn = connect(db)
    previous_session = get_current_session_key()
    try:
        tid = kb.create_task(conn, title="identity fixture", assignee="fixture",
                             workspace_kind="dir", workspace_path=str(workspace))
        kb.recompute_ready(conn)
        task = kb.claim_task(conn, tid)
        _set_worker_pid(conn, tid, os.getpid())
        for key, value in {"HERMES_HOME": str(home), "HERMES_KANBAN_DB": str(db),
                           "HERMES_KANBAN_TASK": tid, "HERMES_KANBAN_RUN_ID": str(task.current_run_id),
                           "HERMES_KANBAN_CLAIM_LOCK": task.claim_lock, "TERMINAL_ENV": "local",
                           "TERMINAL_CWD": str(workspace)}.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("HERMES_DELEGATED_CHILD_CONTEXT", raising=False)
        set_current_session_key("original-session")
        payload = prepare_payload("write_file", [str(target)], ["AGENTS.md"], "identity", content="approved\n")
        request = worker._create_and_pause(conn, payload)
        assert record_human_decision(conn, request.request_id, expected_hash=request.request_hash,
                                    decision=journal.GRANTED, decided_by="fixture-human", decision_surface="desktop")
        file_ops = ft._get_file_ops("identity")
        with monkeypatch.context() as wrong:
            if identity == "session":
                set_current_session_key("foreign-session")
            else:
                key, value = {"profile": ("HERMES_HOME", str(tmp_path / "foreign")),
                              "run": ("HERMES_KANBAN_RUN_ID", str(task.current_run_id + 1)),
                              "claim": ("HERMES_KANBAN_CLAIM_LOCK", "foreign-claim"),
                              "task": ("HERMES_KANBAN_TASK", "t_foreign")}[identity]
                wrong.setenv(key, value)
            with pytest.raises(ValueError, match="does not match"):
                worker._apply_granted_locked(conn, request.request_id, file_ops)
        set_current_session_key("original-session")
        assert journal.get_request(conn, request.request_id).state == journal.GRANTED
        assert target.read_bytes() == b"old\n"
        assert worker._apply_granted_locked(conn, request.request_id, file_ops)["verified"]
        assert target.read_bytes() == b"approved\n"
        with pytest.raises(ValueError, match="already been consumed"):
            worker._apply_granted_locked(conn, request.request_id, file_ops)
    finally:
        set_current_session_key(previous_session)
        conn.close()
