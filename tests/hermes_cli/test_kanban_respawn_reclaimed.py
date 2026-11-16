"""Regressão: um last_failure_error de quota antigo não prende o card se o último run é reclaimed.

Medido em t_482df3f3 (17/10): erro de quota de 12/10 em last_failure_error e último
run reclaimed (#4026) → respawn_guarded blocker_auth para sempre. ``reclaimed`` é
recuperação do dispatcher, não diagnóstico de quota/auth.
"""

import pytest
from pathlib import Path

import hermes_cli.kanban_db as kb
import hermes_cli.kanban_db_connect as kbc
import hermes_cli.kanban_db_dispatch as kbd

QUOTA_TEXT = "pid 85547 exited rate-limited (quota wall) — requeued without counting a failure"


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    """Mesma fixture de tests/hermes_cli/test_kanban_db.py: HERMES_HOME isolado + DB vazio."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def test_reclaimed_run_does_not_keep_stale_quota_blocker(kanban_home, monkeypatch):
    """Erro de quota antigo + último run reclaimed: o guarda não pode devolver blocker_auth."""
    monkeypatch.setenv("HERMES_KANBAN_RATE_LIMIT_COOLDOWN_SECONDS", "0")
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="reclaimed sobre quota antiga", assignee="a")
        conn.execute(
            "INSERT INTO task_runs (task_id, status, outcome, started_at, ended_at) "
            "VALUES (?, 'reclaimed', 'reclaimed', 4999000, 5000000)",
            (tid,),
        )
        conn.execute("UPDATE tasks SET last_failure_error=? WHERE id=?", (QUOTA_TEXT, tid))
        conn.commit()
        assert kbd.check_respawn_guard(conn, tid) != "blocker_auth"
