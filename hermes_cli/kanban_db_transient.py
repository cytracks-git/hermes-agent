"""Re-despacho automatico de bloqueio ``transient`` (roadmap C2, card t_e0d44196).

Um ``kanban_block(kind='transient')`` entra em ``blocked`` com evento ``blocked``
e :func:`kanban_db._has_sticky_block` o trata como sticky: so um humano o tira
de la. Para ``transient`` isso inverte a promessa do proprio tipo ("falha que
pode passar"): medido no board atlas, 7 dias, 43 blocos transient e 0 retomada
automatica (mediana 18,7 min de espera por mao).

Esta varredura devolve o card a fila depois de ``delay_seconds`` com o MESMO
evento ``unblocked`` do caminho humano (payload ``auto='transient_redispatch'``),
para que todo consumidor existente -- requeue do guarda de respawn, notifier,
resume para ``review`` -- trate igual. O handoff chega ao proximo worker porque
``block_task`` grava o motivo como summary do run encerrado, e o contexto do
worker lista esse run em "Prior attempts".

Limites (nao afrouxa nenhum disjuntor):
- uma retomada por evento ``blocked``: depois dela o card sai de ``blocked``;
- ``block_kind``/``block_recurrences`` NAO sao zerados: o segundo bloqueio
  transient seguido cai em ``triage`` via ``block_loop_detected`` como hoje;
- ``consecutive_failures`` NAO e zerado e o limite do breaker e respeitado;
- so bloqueio feito pelo worker (``classified_in_place`` do breaker fica fora);
- so o transient PURO: o ``blocked`` transient tem de ser o ultimo evento de
  ciclo de vida do card. Qualquer evento depois dele fora de
  ``_INFORMATIONAL_EVENT_KINDS`` (``promoted_manual``, ``gave_up``,
  ``promoted``, ``reclaimed``...) desqualifica, fail-closed. Sem isso, um
  promote manual (que grava ``promoted_manual``, nao ``unblocked``) seguido de
  um trip sticky do disjuntor (``force_trip``) deixava o card ``blocked`` com
  ``block_kind='transient'`` herdado e a varredura o devolvia a fila,
  anulando o trip (guardiao t_3066a937);
- trip sticky (``gave_up`` com ``sticky``) sem ``unblocked`` humano depois
  tambem desqualifica, mesmo que anterior ao bloqueio: o disjuntor pediu
  operador e so um ``unblocked`` o libera, como em ``_has_sticky_block``;
- pais abertos re-gateiam para ``todo``.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Optional

from hermes_cli import kanban_db as _kb

DEFAULT_TRANSIENT_REDISPATCH_SECONDS = 600
AUTO_MARKER = "transient_redispatch"

# Eventos que nunca mudam o status do card: podem aparecer depois do
# ``blocked`` transient sem tirar a elegibilidade. Lista fechada de proposito:
# evento novo de ciclo de vida desqualifica ate ser classificado aqui.
_INFORMATIONAL_EVENT_KINDS = (
    "commented", "attached", "edited", "reprioritized", "linked", "unlinked",
    "delivery", "heartbeat",
)


def _is_pure_transient_block(conn: sqlite3.Connection, task_id: str, blocked_event_id: int) -> bool:
    """True so quando nada alem de evento informativo veio depois do ``blocked``
    transient e nao ha trip sticky pendente de ``unblocked`` humano."""
    marks = ", ".join("?" for _ in _INFORMATIONAL_EVENT_KINDS)
    later = conn.execute(
        f"SELECT 1 FROM task_events WHERE task_id = ? AND id > ? AND kind NOT IN ({marks}) LIMIT 1",
        (task_id, blocked_event_id, *_INFORMATIONAL_EVENT_KINDS),
    ).fetchone()
    if later is not None:
        return False
    trips = conn.execute(
        "SELECT payload FROM task_events WHERE task_id = ? AND kind = 'gave_up' AND id > COALESCE("
        "  (SELECT MAX(id) FROM task_events WHERE task_id = ? AND kind = 'unblocked'), 0)",
        (task_id, task_id),
    ).fetchall()
    return not any(_kb._json_dict(t["payload"]).get("sticky") for t in trips)


def resolve_transient_redispatch_seconds(kanban_cfg: Optional[dict] = None) -> int:
    """``kanban.transient_redispatch_seconds`` (0 = desligado). Valor invalido
    ou negativo desliga: re-despacho e opt-out explicito, nunca palpite."""
    if kanban_cfg is None:
        try:
            from hermes_cli.config import load_config

            kanban_cfg = load_config().get("kanban") or {}
        except Exception:
            kanban_cfg = {}
    raw = (kanban_cfg or {}).get("transient_redispatch_seconds", DEFAULT_TRANSIENT_REDISPATCH_SECONDS)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def redispatch_transient_blocks(
    conn: sqlite3.Connection, *, delay_seconds: int, failure_limit: int,
    now: Optional[int] = None,
) -> list[str]:
    """Devolve a fila os cards ``blocked`` por ``transient`` ha >= ``delay_seconds``.
    Retorna os ids retomados. ``delay_seconds <= 0`` nao faz nada. Abre a propria
    transacao -- chamar FORA de qualquer write txn."""
    if delay_seconds <= 0:
        return []
    now = int(time.time()) if now is None else int(now)
    resumed: list[str] = []
    with _kb.write_txn(conn):
        rows = conn.execute(
            "SELECT id, consecutive_failures, max_retries FROM tasks "
            "WHERE status = 'blocked' AND block_kind = 'transient' AND current_run_id IS NULL"
        ).fetchall()
        for row in rows:
            task_id = row["id"]
            last = conn.execute(
                "SELECT id, kind, payload, created_at FROM task_events "
                "WHERE task_id = ? AND kind IN ('blocked', 'unblocked', 'block_loop_detected') "
                "ORDER BY id DESC LIMIT 1", (task_id,),
            ).fetchone()
            if last is None or last["kind"] != "blocked":
                continue
            if _kb._json_dict(last["payload"]).get("classified_in_place"):
                continue
            if not _is_pure_transient_block(conn, task_id, int(last["id"])):
                continue
            if now - int(last["created_at"] or 0) < delay_seconds:
                continue
            fallback = failure_limit if failure_limit is not None else _kb.DEFAULT_FAILURE_LIMIT
            limit = int(row["max_retries"]) if row["max_retries"] is not None else int(fallback)
            if int(row["consecutive_failures"] or 0) >= limit:
                continue
            resume_status = _kb._resume_status_from_events(conn, task_id)
            landing = _kb._landing_status_after_parents(conn, task_id)
            new_status = "review" if landing == "ready" and resume_status == "review" else landing
            cur = conn.execute(
                "UPDATE tasks SET status = ? WHERE id = ? AND status = 'blocked' "
                "AND block_kind = 'transient' AND current_run_id IS NULL",
                (new_status, task_id),
            )
            if cur.rowcount != 1:
                continue
            _kb._append_event(conn, task_id, "unblocked", {
                "status": new_status, "resume_status": resume_status, "auto": AUTO_MARKER,
                "blocked_event_id": int(last["id"]), "delay_seconds": int(delay_seconds),
                "waited_seconds": now - int(last["created_at"] or 0),
            })
            resumed.append(task_id)
    return resumed
