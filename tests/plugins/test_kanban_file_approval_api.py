"""API humana em banco isolado: autenticação real e decisão vinculada ao hash."""
from contextlib import closing, contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_approvals as journal
from hermes_cli.kanban_db_connect import connect
from plugins.kanban.dashboard.approval_api import create_approval_router


def test_board_counter_reads_pending_journal_not_filtered_cards(tmp_path, monkeypatch):
    from plugins.kanban.dashboard import plugin_api
    db = kb.init_db(db_path=tmp_path / "counter.db")
    monkeypatch.setenv("HERMES_KANBAN_DB", str(db))
    app = FastAPI()
    app.include_router(plugin_api.router)
    client = TestClient(app)
    with closing(connect(db)) as conn:
        tid = kb.create_task(conn, title="counter fixture", assignee="fixture", tenant="hidden")
        kb.recompute_ready(conn)
        task = kb.claim_task(conn, tid)
        with kb.write_txn(conn):
            item = journal.create_request(
                conn, task_id=tid, run_id=task.current_run_id, claim_lock=task.claim_lock,
                profile_home=str(tmp_path), session_key="fixture", workspace_path=str(tmp_path),
                created_by_pid=123, created_by_started_at="fixture", payload={"targets": []})
            kb.pause_for_approval(conn, tid, request_id=item.request_id,
                                  request_hash=item.request_hash, expected_run_id=task.current_run_id)
        board = client.get("/board?tenant=other").json()
        assert not any(column["tasks"] for column in board["columns"])
        assert board["pending_approvals"] == 1
        with kb.write_txn(conn):
            journal.decide_request(conn, item.request_id, decision=journal.GRANTED,
                                   decided_by="fixture-human", decision_surface="desktop")
        assert kb.get_task(conn, tid).status == "waiting_approval"
        assert client.get("/board").json()["pending_approvals"] == 0


@pytest.mark.parametrize("decision", ["granted", "denied", "cancelled"])
def test_authenticated_decision_is_exact_and_not_generic_status(tmp_path, decision):
    from hermes_cli import web_server
    db = kb.init_db(db_path=tmp_path / "isolated.db")
    with closing(connect(db)) as conn:
        tid = kb.create_task(conn, title="API fixture", assignee="fixture")
        kb.recompute_ready(conn)
        task = kb.claim_task(conn, tid)
        with kb.write_txn(conn):
            item = journal.create_request(
                conn, task_id=tid, run_id=task.current_run_id, claim_lock=task.claim_lock,
                profile_home=str(tmp_path), session_key="fixture", workspace_path=str(tmp_path),
                created_by_pid=123, created_by_started_at="fixture", payload={"targets": [], "op": "write_file"})
            kb.pause_for_approval(conn, tid, request_id=item.request_id,
                                  request_hash=item.request_hash, expected_run_id=task.current_run_id)

    @contextmanager
    def board_conn(board):
        assert board == "fixture-board"
        with closing(connect(db)) as conn:
            yield board, conn

    app = FastAPI()
    app.include_router(create_approval_router(board_conn))
    client = TestClient(app)
    path = f"/tasks/{tid}/approvals/{item.request_id}/decision?board=fixture-board"
    body = {"decision": decision, "request_hash": item.request_hash}
    assert client.post(path, json=body).status_code == 401
    # Token efêmero gerado pelo servidor da fixture; nunca persistido na evidência.
    client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    assert client.post(path, json={**body, "decided_by": "H1"}).status_code == 422
    assert client.post(path, json={**body, "request_hash": "0" * 64}).status_code == 409
    assert client.post(path.replace(tid, "wrong-task"), json=body).status_code == 404
    listed = client.get(f"/tasks/{tid}/approvals?board=fixture-board")
    assert listed.status_code == 200
    assert listed.json()["approvals"][0]["request_hash"] == item.request_hash
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["approval"]["decided_by"] == "local-session-owner"
    assert response.json()["approval"]["state"] == decision
    assert client.post(path, json=body).status_code == 409
    with closing(connect(db)) as conn:
        assert journal.get_request(conn, item.request_id).applied_at is None
        expected = "waiting_approval" if decision == "granted" else "blocked"
        assert kb.get_task(conn, tid).status == expected
