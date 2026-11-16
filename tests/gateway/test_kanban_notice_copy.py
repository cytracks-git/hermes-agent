"""Kanban terminal-event pings must say what state the task is in and name the next command.

`gave_up` means the dispatcher auto-blocked the task (spawn failure, crash or timeout alike) and a
human must act; `crashed`/`timed_out` retry on their own. Contract tests over
`_EVENT_FORMATTERS`, never whole-string snapshots.
"""

from types import SimpleNamespace

from gateway.kanban_watchers_notifier import _EVENT_FORMATTERS


def _names(task_id="T-123"):
    return SimpleNamespace(task_id=task_id, head=f"[board] Kanban {task_id}", title="Ship it", board_tag="[board] ")


def _event(**payload):
    return SimpleNamespace(payload=payload)


def test_gave_up_says_blocked_and_names_unblock_log_reassign():
    msg, _wake, _reason = _EVENT_FORMATTERS["gave_up"](
        _event(failures=3, error="spawn: profile 'coder' not found"), _names())
    assert "blocked" in msg.lower()
    assert "3 times" in msg
    assert "spawn: profile 'coder' not found" in msg
    for cmd in ("hermes kanban unblock T-123", "hermes kanban log T-123", "hermes kanban reassign T-123"):
        assert f"`{cmd}`" in msg
    assert "spawn failures" not in msg  # wrong for crash/timeout-triggered trips


def test_crashed_and_timed_out_say_retry_and_hide_internals():
    crashed, *_ = _EVENT_FORMATTERS["crashed"](_event(), _names())
    timed_out, *_ = _EVENT_FORMATTERS["timed_out"](_event(limit_seconds=1800), _names())
    for msg in (crashed, timed_out):
        assert "retried automatically" in msg
        assert "pid" not in msg and "max_runtime" not in msg
    assert "30-minute" in timed_out


def test_persisted_file_approval_notifies_without_waking_a_model(tmp_path):
    import json
    from contextlib import closing
    from hermes_cli import kanban_db as kb
    from hermes_cli.kanban_db_connect import connect
    from gateway.kanban_watchers_notifier import TERMINAL_KINDS, _WAKE_KINDS

    with closing(connect(kb.init_db(db_path=tmp_path / "board.db"))) as conn:
        tid = kb.create_task(conn, title="Notification fixture", assignee="fixture")
        kb.recompute_ready(conn)
        task = kb.claim_task(conn, tid)
        assert kb.pause_for_approval(conn, tid, request_id="fixture-request", request_hash="f" * 64,
                                     expected_run_id=task.current_run_id, targets=["AGENTS.md"])
        row = conn.execute("SELECT kind,payload FROM task_events WHERE task_id=? ORDER BY id DESC LIMIT 1", (tid,)).fetchone()
        assert row["kind"] in TERMINAL_KINDS
        assert row["kind"] not in _WAKE_KINDS
        message, wake, _ = _EVENT_FORMATTERS[row["kind"]](
            _event(**json.loads(row["payload"])), _names(tid))
        assert "fixture-request" in message and tid in message
        assert "approve once" in message and "Comments do not authorize" in message
        assert wake is None
