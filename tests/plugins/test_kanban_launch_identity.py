"""Identidade de lançamento: leitura preservada, escrita cercada e recuperação humana.

HTTP usa o router de produção e SQLite real. TestClient substitui apenas o socket;
nenhum resultado de mutação, predicado de identidade ou registro é fabricado.
"""
import importlib.util
import os
from contextlib import nullcontext
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from agent.delegation_context import DELEGATED_CHILD_ENV_MARKER, delegated_child_context
from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect_closing


@pytest.fixture
def board_client(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home))
    monkeypatch.delenv(DELEGATED_CHILD_ENV_MARKER, raising=False)
    kb.init_db()
    path = Path(__file__).resolve().parents[2] / "plugins/kanban/dashboard/plugin_api.py"
    spec = importlib.util.spec_from_file_location("kanban_launch_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router, prefix="/api/plugins/kanban")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield home, client


@pytest.mark.parametrize("identity", ["inherited", "legacy", "in_process", "profile"])
def test_restricted_launch_is_readable_but_never_promoted(board_client, monkeypatch, identity):
    home, client = board_client
    with connect_closing() as conn:
        task = kb.create_task(conn, title="Restricted launch", initial_status="blocked")
        before = kb.list_events(conn, task)
    if identity == "profile":
        profile = home / "profiles" / "writer"
        profile.mkdir(parents=True)
        monkeypatch.setenv("HERMES_HOME", str(profile))
    marker = "1" if identity == "legacy" else str(home)
    if identity != "in_process":
        monkeypatch.setenv(DELEGATED_CHILD_ENV_MARKER, marker)
    context = delegated_child_context() if identity == "in_process" else nullcontext()
    api = "/api/plugins/kanban"
    with context:
        response = client.patch(f"{api}/tasks/{task}", json={"status": "ready"})
        assert response.status_code == 403, response.text
        assert "operating system" in response.json()["detail"]
        assert "agent" in response.json()["detail"]
        board = client.get(f"{api}/board")
        assert board.status_code == 200, board.text
        assert board.json()["write_access"]["allowed"] is False
        assert board.json()["write_access"]["reason"] == response.json()["detail"]
        assert client.post(f"{api}/tasks/bulk", json={"ids": [task], "status": "ready"}).status_code == 403
        with connect_closing() as conn:
            assert kb.get_task(conn, task).status == "blocked"
            assert kb.list_events(conn, task) == before
            with pytest.raises(PermissionError):
                kb.unblock_task(conn, task)
    if identity != "in_process":
        assert os.environ[DELEGATED_CHILD_ENV_MARKER] == marker


def test_operator_and_isolated_lab_keep_parent_and_review_gates(board_client, monkeypatch, tmp_path):
    _, client = board_client
    api = "/api/plugins/kanban"
    # A restrição de outra raiz não contamina este lab nem o processo humano.
    for marker in (None, str(tmp_path / "other-board")):
        if marker:
            monkeypatch.setenv(DELEGATED_CHILD_ENV_MARKER, marker)
        with connect_closing() as conn:
            parent = kb.create_task(conn, title="Open parent", initial_status="blocked")
            child = kb.create_task(conn, title="Dependent", parents=[parent], initial_status="blocked")
            free = kb.create_task(conn, title="Independent", initial_status="blocked")
        assert client.get(f"{api}/board").json()["write_access"]["allowed"] is True
        assert client.patch(f"{api}/tasks/{free}", json={"status": "ready"}).status_code == 200
        assert client.patch(f"{api}/tasks/{child}", json={"status": "ready"}).status_code == 200
        with connect_closing() as conn:
            assert kb.get_task(conn, free).status == "ready"
            assert kb.get_task(conn, child).status == "todo"
            assert kb.request_review(conn, free, summary="Needs independent review")
        assert client.patch(f"{api}/tasks/{free}", json={"status": "ready"}).status_code == 200
        with connect_closing() as conn:
            kinds = [event.kind for event in kb.list_events(conn, free)]
            assert "review_reopened" in kinds
            assert "completed" not in kinds
