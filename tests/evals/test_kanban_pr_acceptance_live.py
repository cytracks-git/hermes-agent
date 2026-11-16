"""Isolation contract of evals/kanban_pr_acceptance_live.py.

The eval creates fixture tasks (completion_contract='acme/repo', PR pull/7).
Run from inside a kanban worker it inherits HERMES_KANBAN_DB/BOARD/HOME and a
TMPDIR under the real Hermes home; before the fix those fixtures landed on the
live board. Here a fake "real" Hermes root stands in for the live one: the eval
must leave its board untouched, and exit 2 when no isolated location exists.
"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = ROOT / "evals" / "kanban_pr_acceptance_live.py"


def _worker_env(tmp_path: Path) -> tuple[dict, Path]:
    """Environment a dispatcher injects into a worker on board ``live``."""
    real_root = tmp_path / ".hermes"
    profile = real_root / "profiles" / "executor"
    scratch = profile / "cache" / "scratch"
    board_db = real_root / "kanban" / "boards" / "live" / "kanban.db"
    scratch.mkdir(parents=True)
    board_db.parent.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_")}
    env.update(
        HOME=str(tmp_path),
        HERMES_HOME=str(profile),
        HERMES_KANBAN_HOME=str(real_root),
        HERMES_KANBAN_BOARD="live",
        HERMES_KANBAN_DB=str(board_db),
        TMPDIR=str(scratch),
    )
    subprocess.run(
        [sys.executable, "-c", "from hermes_cli import kanban_db as kb; kb.init_db()"],
        cwd=ROOT, env=env, check=True,
    )
    return env, board_db


def _task_count(db: Path) -> int:
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        return conn.execute("SELECT count(*) FROM tasks").fetchone()[0]


def _boards_under(root: Path) -> set[Path]:
    return {p for p in root.rglob("kanban.db")}


def test_eval_with_live_board_pins_writes_nothing_to_the_live_board(tmp_path):
    env, board_db = _worker_env(tmp_path)
    before_count, before_boards = _task_count(board_db), _boards_under(tmp_path)

    proc = subprocess.run([sys.executable, str(EVAL), str(ROOT)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=300)

    # controle positivo: o eval rodou de verdade e produziu os casos
    assert proc.returncode == 0, proc.stderr
    assert '"case": "success"' in proc.stdout
    # controle negativo: nenhum card e nenhum board novo sob a raiz "real"
    assert _task_count(board_db) == before_count
    assert _boards_under(tmp_path) == before_boards


def test_eval_fails_closed_when_no_isolated_location_exists(tmp_path):
    env, board_db = _worker_env(tmp_path)
    # um pin cuja pasta e a raiz do filesystem protege qualquer tmpdir possivel
    env["HERMES_KANBAN_DB"] = str(Path(board_db.anchor) / "kanban.db")
    before = _task_count(board_db)

    proc = subprocess.run([sys.executable, str(EVAL), str(ROOT)], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=300)

    assert proc.returncode == 2, (proc.returncode, proc.stderr)
    assert '"isolation": "failed"' in proc.stderr
    assert _task_count(board_db) == before
