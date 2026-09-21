"""Serve real: worker herdado não vira operador; relançamento independente recupera."""
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading

import httpx

from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect_closing


def test_serve_launch_identity_and_independent_recovery(tmp_path, monkeypatch):
    root = tmp_path / ".hermes"
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    with connect_closing() as conn:
        task = kb.create_task(conn, title="Real launch lifecycle", initial_status="blocked")
    # Simula um ambiente de login novo, não uma função que higieniza filhos.
    login_env = {
        "PATH": os.environ["PATH"], "HOME": str(tmp_path),
        "HERMES_HOME": str(root), "HERMES_KANBAN_HOME": str(root),
        "HERMES_SERVE_HEADLESS": "1", "PYTHONUNBUFFERED": "1",
        "HERMES_DASHBOARD_SESSION_TOKEN": "local-launch-test",
    }
    profile = root / "profiles" / "writer"
    profile.mkdir(parents=True)
    repo = Path(__file__).resolve().parents[2]
    # Default, perfil herdado e processo humano novo usam o MESMO SQLite.
    for inherited, home in ((True, root), (True, profile), (False, root)):
        env = {**login_env, "HERMES_HOME": str(home)}
        if inherited:
            env["HERMES_DELEGATED_CHILD_CONTEXT"] = str(root)
        proc = subprocess.Popen(
            [sys.executable, "-m", "hermes_cli.main", "serve", "--port", "0"],
            cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        lines = []
        ready = queue.Queue()

        def drain():
            for line in proc.stdout:
                lines.append(line)
                match = re.search(r"HERMES_BACKEND_READY port=(\d+)", line)
                if match:
                    ready.put(int(match[1]))
            ready.put(None)

        thread = threading.Thread(target=drain, daemon=True)
        thread.start()
        try:
            try:
                port = ready.get(timeout=30)
            except queue.Empty:
                raise AssertionError("Backend did not become ready:\n" + "".join(lines))
            assert port, "".join(lines)
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10,
                              headers={"X-Hermes-Session-Token": "local-launch-test"}) as client:
                board = client.get("/api/plugins/kanban/board")
                assert board.status_code == 200, board.text
                assert board.json()["write_access"]["allowed"] is not inherited
                changed = client.patch(f"/api/plugins/kanban/tasks/{task}", json={"status": "ready"})
                assert changed.status_code == (403 if inherited else 200), changed.text
            with connect_closing() as conn:
                assert kb.get_task(conn, task).status == ("blocked" if inherited else "ready")
            if inherited:
                assert "Kanban is read-only for this launch" in "".join(lines)
            print(f"LIVE inherited={inherited} profile={home.name} board=200 mutation={changed.status_code}")
        finally:
            proc.terminate()
            proc.wait(timeout=15)
            thread.join(timeout=5)
