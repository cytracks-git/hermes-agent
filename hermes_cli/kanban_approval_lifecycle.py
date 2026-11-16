"""Transições e recuperação do journal, compartilhadas pela UI e dispatcher."""
from __future__ import annotations

import time

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_approvals as journal


def record_human_decision(conn, request_id: str, *, expected_hash: str,
                          decision: str, decided_by: str, decision_surface: str) -> bool:
    """A superfície autenticada fornece autoria; o payload HTTP não escolhe identidade."""
    with kb.write_txn(conn):
        request = journal.get_request(conn, request_id)
        if request is None:
            return False
        task = kb.get_task(conn, request.task_id)
        if (task is None or task.status != "waiting_approval"
                or task.current_run_id != request.run_id):
            return False
        if not journal.decide_request(conn, request_id, expected_hash=expected_hash,
                                      decision=decision, decided_by=decided_by,
                                      decision_surface=decision_surface):
            return False
        if decision == journal.GRANTED:
            kb._append_event(conn, request.task_id, "approval_granted",
                             {"request_id": request_id, "request_hash": expected_hash},
                             run_id=request.run_id)
        else:
            kb.end_approval_wait(conn, request.task_id, request_id=request_id,
                                 expected_run_id=request.run_id, outcome=decision,
                                 reason=f"Human decision: {decision}")
        return True


def reconcile_approval_orphans(conn) -> list[str]:
    from hermes_cli.kanban_db_dispatch import _worker_alive, TERMINAL_WORKER_REAP_GRACE_SECONDS
    now = int(time.time())
    recovered = []
    with kb.write_txn(conn):
        rows = conn.execute(
            "SELECT a.* FROM approval_requests a JOIN tasks t ON t.id=a.task_id "
            "WHERE t.status='waiting_approval' AND t.current_run_id=a.run_id "
            "AND (a.state IN ('pending','granted','consumed'))").fetchall()
        for row in rows:
            request = journal._row_to_request(row)
            if now - request.created_at < TERMINAL_WORKER_REAP_GRACE_SECONDS:
                continue
            if _worker_alive(request.created_by_pid, request.created_by_started_at):
                continue
            reason = ("Worker gone after write receipt; inspect before retrying"
                      if request.applied_at is not None else "Worker gone; approval cannot be replayed")
            if request.applied_at is None:
                journal.mark_orphaned(conn, request.request_id)
            if kb.end_approval_wait(conn, request.task_id, request_id=request.request_id,
                                    expected_run_id=request.run_id, outcome="orphaned", reason=reason):
                recovered.append(request.task_id)
    return recovered
