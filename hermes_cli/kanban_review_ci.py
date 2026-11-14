"""CI follow-up card born from a review handoff that names a published PR.

Waiting for CI used to live on the implementation card: the implementer
blocked "transient: required 8/9, retry later", got unblocked, blocked again
for the same cause, and the second block routed the card to triage
(``block_loop_detected``). The wait belongs on its own card whose completion
is gated by the PR contract (``kanban_pr_acceptance``: exact head, latest run
per required check), so the implementation card can finish its review and the
CI verdict cannot be satisfied by an old head or a superseded rerun.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

from hermes_cli.kanban_pr_acceptance import _PR

_SHA = re.compile(r"[0-9a-f]{40}")


def ci_child_spec(task_id: str, metadata: object, reviewer: Optional[str],
                  implementer: Optional[str]) -> Optional[dict]:
    """``create_task`` kwargs for the ``[ci]`` child, or ``None`` when the
    handoff does not name a PR or the only candidate verifier is the author."""
    if not isinstance(metadata, dict):
        return None
    pr = metadata.get("published_pr")
    match = _PR.fullmatch(pr) if isinstance(pr, str) else None
    # Never route the CI verdict back to the author: a card the author would
    # sign is worse than no card (the parent review still happens).
    if not match or not reviewer or reviewer == implementer:
        return None
    head = metadata.get("head_sha")
    head = head if isinstance(head, str) and _SHA.fullmatch(head) else None
    number = match[2]
    title = f"[ci] PASSA final do PR #{number}" + (f" no head {head[:8]}" if head else "")
    body = (
        f"Card de CI do card {task_id} (pedido de revisao com PR publicado).\n"
        f"PR: {pr}\n"
        f"Head no pedido: {head or 'NAO INFORMADO (medir o head vivo)'}\n\n"
        "Fecha so quando o head VIVO do PR tiver todos os required verdes, "
        "decididos pelo run MAIS RECENTE de cada check nesse head. Sucesso em "
        "head antigo ou rerun superado nao conta. O contrato de conclusao deste "
        "card e o proprio PR: kanban_complete recusa enquanto o CI do head atual "
        "nao passa e grava o recibo pr_acceptance.\n"
        f"Concluir com metadata.published_pr={pr}.\n"
        f"Nasce em todo e so roda depois que {task_id} fecha (revisao do miolo). "
        f"Implementador: {implementer or 'NAO MEDIDO'}; este card nunca vai a ele."
    )
    return {
        "title": title,
        "body": body,
        "assignee": reviewer,
        "created_by": "kanban_request_review",
        "creator_task_id": task_id,
        "parents": (task_id,),
        "workspace_kind": "scratch",
        "completion_contract": pr,
        # One CI card per (implementation card, PR): re-review after changes
        # reuses it; the contract measures the live head, not the one above.
        "idempotency_key": f"review-ci:{task_id}:{pr}",
    }


def spawn_ci_child(conn: sqlite3.Connection, task_id: str, metadata: object,
                   reviewer: Optional[str], implementer: Optional[str]) -> Optional[str]:
    """Create (or reuse) the ``[ci]`` child inside the caller's write txn."""
    spec = ci_child_spec(task_id, metadata, reviewer, implementer)
    if spec is None:
        return None
    from hermes_cli.kanban_db import create_task

    return create_task(conn, **spec)
