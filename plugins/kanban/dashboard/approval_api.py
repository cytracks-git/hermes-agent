"""Superfície humana do journal. Não registrada como ferramenta de modelo."""
from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from hermes_cli import kanban_approval_diagnostics as diagnostics
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_approvals as journal
from hermes_cli.kanban_approval_lifecycle import record_human_decision


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["granted", "denied", "cancelled"]


def _human_identity(request: Request) -> str:
    from hermes_cli.web_server import _require_token
    if getattr(request.state, "token_authenticated", False):
        raise HTTPException(403, "Service credentials cannot decide human approvals")
    _require_token(request)
    session = getattr(request.state, "session", None)
    if session is not None:
        return f"{session.provider}:{session.user_id}"
    # O token de sessão local é o principal autenticado, não uma identidade
    # enviada pelo formulário. Não registrar o próprio segredo no journal.
    return "local-session-owner"


def create_approval_router(db_conn) -> APIRouter:
    router = APIRouter()

    @router.get("/tasks/{task_id}/approvals")
    def task_approvals(task_id: str, request: Request, board: str | None = None):
        _human_identity(request)
        with db_conn(board) as (_, conn):
            if kb.get_task(conn, task_id) is None:
                raise HTTPException(404, "Task not found")
            # ``diagnostics`` é projeção derivada, ao lado do registro imutável:
            # o payload e o hash que o humano aprova seguem byte a byte iguais.
            return {"approvals": [
                {**asdict(item), "diagnostics": diagnostics.project(conn, item)}
                for item in journal.list_requests(conn, task_id=task_id)]}

    @router.post("/tasks/{task_id}/approvals/{request_id}/notice-retry")
    def notice_retry(task_id: str, request_id: str, request: Request, board: str | None = None):
        """Reabre o orçamento de AVISO. Não decide, não reenvia escrita.

        Exige o mesmo principal humano do endpoint de decisão: credencial de
        serviço não pode mexer no orçamento de aviso de um pedido humano.
        """
        _human_identity(request)
        with db_conn(board) as (_, conn):
            item = journal.get_request(conn, request_id)
            if item is None or item.task_id != task_id:
                raise HTTPException(404, "Approval not found on this task and board")
            diagnostics.request_notice_retry(
                conn, task_id=task_id, run_id=item.run_id, request_id=request_id)
            refreshed = journal.get_request(conn, request_id) or item
            return {"approval": {**asdict(refreshed),
                                 "diagnostics": diagnostics.project(conn, refreshed)}}

    @router.post("/tasks/{task_id}/approvals/{request_id}/decision")
    def decide(task_id: str, request_id: str, body: ApprovalDecision,
               request: Request, board: str | None = None):
        actor = _human_identity(request)
        with db_conn(board) as (_, conn):
            item = journal.get_request(conn, request_id)
            if item is None or item.task_id != task_id:
                raise HTTPException(404, "Approval not found on this task and board")
            if not record_human_decision(
                    conn, request_id, expected_hash=body.request_hash,
                    decision=body.decision, decided_by=actor, decision_surface="dashboard"):
                raise HTTPException(409, "Approval changed or was already decided; refresh before retrying")
            decided = journal.get_request(conn, request_id)
            if decided is None:
                # A linha sumiu entre o UPDATE e esta leitura: a decisão foi
                # gravada, mas não há registro para devolver. Não fabricar um.
                raise HTTPException(409, "Approval record disappeared after the decision; refresh the task")
            return {"approval": {**asdict(decided),
                                 "diagnostics": diagnostics.project(conn, decided)}}

    return router
