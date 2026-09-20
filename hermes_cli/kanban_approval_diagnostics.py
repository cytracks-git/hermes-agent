"""Diagnostico contextual da espera de aprovacao humana (card t_78aaa333, 1057/1058).

Por que existe
--------------
Antes disto, ``tools/file_approval_worker.apply_granted`` devolvia ``None`` para
CINCO causas distintas -- lock do dispatcher, orcamento do board, orcamento do
host, pressao de memoria e capacidade por perfil -- e ``_wait`` nao registrava
nenhuma delas. Um operador via ``granted`` parado e nao tinha como separar
"esperando vaga" de "travou". O H1 pediu controle contra demoras longas e
REJEITOU alarme por relogio (comentario 1058): tempo isolado nao caracteriza
defeito.

Entao a regra aqui e: **evento so nasce quando muda etapa, motivo, evidencia ou
tentativa.** Passagem do relogio nunca cria linha. Um poll repetido sobre o
mesmo estado e silencioso por construcao -- e e isso que impede o loop de
alertas que o 1058 proibiu.

O que NAO acontece aqui
-----------------------
Nenhuma decisao, nenhum kill, nenhum redispatch, nenhum auto-approve. Este
modulo so ESCREVE OBSERVACAO e LE projecao. A autoridade continua no journal
(``kanban_db_approvals``) e na superficie humana autenticada.

O evento ``approval_progress`` fica de fora de ``TERMINAL_KINDS`` /
``_WAKE_KINDS`` (gateway) e de ``_KANBAN_NOTIFY_KINDS`` (TUI) de proposito:
diagnostico nao acorda modelo nem vira mensagem. Quem quiser ver, olha o card.
"""

from __future__ import annotations

import sqlite3
from typing import Any
from typing import Optional

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_approvals as journal


# Evento de observacao. Nome proprio para que nenhuma varredura existente o
# confunda com transicao de estado: ele NAO muda nada.
PROGRESS_KIND = "approval_progress"
# Reabertura de orcamento de aviso pedida por um humano ("Retry notice").
NOTICE_RETRY_KIND = "approval_notice_retry"

# --- Etapas (phase) ---------------------------------------------------------
AWAITING_HUMAN = "awaiting_human"
AWAITING_ADMISSION = "awaiting_admission"
APPLYING = "applying"
APPLIED = "applied"
WRITE_RECEIPT_PENDING = "write_receipt_pending"
CLOSED = "closed"
NOTICE = "notice"

# --- Motivos (reason_code) --------------------------------------------------
HUMAN_DECISION_PENDING = "human_decision_pending"
# Motivo da recusa de admissao, produzido pela MESMA avaliacao sob o lock do
# dispatcher (nunca recalculado depois, nunca adivinhado pelo frontend).
DISPATCHER_LOCK = "dispatcher_lock"
BOARD_CAPACITY = "board_capacity"
HOST_CAPACITY = "host_capacity"
PROFILE_CAPACITY = "profile_capacity"
MEMORY_PRESSURE = "memory_pressure"
# ``granted`` sem NENHUMA observacao de admissao. Nao e "capacidade cheia": e
# "ainda nao observei". Chutar capacidade aqui seria a mentira que o 1058 veta.
RESUME_REASON_NOT_YET_OBSERVED = "resume_reason_not_yet_observed"
APPLICATION_OUTCOME_NOT_CONFIRMED = "application_outcome_not_yet_confirmed"
WRITE_VERIFIED = "write_verified"
DECISION_CLOSED = "decision_closed"
# Entrega do aviso.
NOTICE_DELIVERED = "notice_delivered"
NOTICE_DELIVERY_FAILED = "notice_delivery_failed"
NOTICE_BUDGET_EXHAUSTED = "notice_budget_exhausted"

ADMISSION_REASONS = (
    DISPATCHER_LOCK, BOARD_CAPACITY, HOST_CAPACITY, PROFILE_CAPACITY, MEMORY_PRESSURE,
)

# Texto que o ADMINISTRADOR le -- em ingles (regra 12-G). Comentario em pt-BR.
# "Next action" responde "o que destrava isto", nunca "quanto falta": nao ha
# previsao honesta de quando um humano responde.
NEXT_ACTION: dict[str, str] = {
    HUMAN_DECISION_PENDING: "Approve or deny this exact content on the card.",
    DISPATCHER_LOCK: "Nothing to do; another dispatcher tick holds the board lock.",
    BOARD_CAPACITY: "Free a running task on this board, or raise kanban.max_spawn.",
    HOST_CAPACITY: "Free a running task on this host, or raise kanban.max_in_progress.",
    PROFILE_CAPACITY: "Free a running task for this assignee, or raise "
                      "kanban.max_in_progress_per_profile.",
    MEMORY_PRESSURE: "Nothing to do; the host is under memory pressure and admits no new work.",
    RESUME_REASON_NOT_YET_OBSERVED: "Nothing to do; the worker has not reported an admission "
                                    "attempt yet.",
    APPLICATION_OUTCOME_NOT_CONFIRMED: "Do not retry. Inspect the target files before any "
                                       "further action.",
    WRITE_VERIFIED: "None; the approved content was written and verified.",
    DECISION_CLOSED: "None; this request is closed and cannot be applied.",
    NOTICE_DELIVERED: "None; the notice reached the transport.",
    NOTICE_DELIVERY_FAILED: "Reconnect the session that owns this task's subscription.",
    NOTICE_BUDGET_EXHAUSTED: "Reconnect the session, or use Retry notice to open a new "
                             "delivery budget.",
}

# Rotulo curto da etapa, tambem em ingles.
PHASE_LABEL: dict[str, str] = {
    AWAITING_HUMAN: "Human decision pending",
    AWAITING_ADMISSION: "Approved; waiting for a dispatch slot",
    APPLYING: "Applying the approved content",
    APPLIED: "Written and verified",
    WRITE_RECEIPT_PENDING: "Consumed; write receipt not yet confirmed",
    CLOSED: "Closed",
    NOTICE: "Notice delivery",
}

DEFAULT_NOTICE_MAX_ATTEMPTS = 3


def resolve_notice_max_attempts() -> int:
    """``kanban.approval_notice_max_attempts``, saneado.

    Orcamento por GERACAO de transporte, nao por pedido: uma conexao morta nao
    deve consumir para sempre o orcamento da proxima. Valor invalido/ausente cai
    no default -- um limite quebrado nunca pode virar "tentar infinito".
    """
    try:
        from hermes_cli.config import load_config_readonly
        raw = (load_config_readonly() or {}).get("kanban", {}).get("approval_notice_max_attempts")
    except Exception:
        return DEFAULT_NOTICE_MAX_ATTEMPTS
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_NOTICE_MAX_ATTEMPTS
    return value if value >= 1 else DEFAULT_NOTICE_MAX_ATTEMPTS


def last_evidence(conn: sqlite3.Connection, task_id: str, run_id: Optional[int]) -> tuple[
        Optional[int], Optional[int]]:
    """``(event_id, created_at)`` do ultimo evento REAL deste card.

    ``approval_progress`` e o proprio diagnostico e e excluido: incluir faria a
    observacao se alimentar -- cada poll veria "evidencia nova" que ela mesma
    acabou de escrever, e a deduplicacao abaixo nunca silenciaria nada.

    Eventos com ``run_id IS NULL`` contam: sao de escopo de TAREFA (comentario,
    link, mudanca de status) e sao evidencia tao real quanto os do run. Filtrar
    so pelo run escondia exatamente as acoes humanas que acontecem enquanto a
    aprovacao espera -- que e o caso de uso desta coluna.
    """
    row = conn.execute(
        "SELECT id, created_at FROM task_events "
        " WHERE task_id = ? AND kind NOT IN (?, ?) "
        "   AND (? IS NULL OR run_id = ? OR run_id IS NULL) "
        " ORDER BY id DESC LIMIT 1",
        (task_id, PROGRESS_KIND, NOTICE_RETRY_KIND, run_id, run_id),
    ).fetchone()
    if row is None:
        return None, None
    return int(row["id"]), int(row["created_at"])


def _last_progress(conn: sqlite3.Connection, request_id: str) -> Optional[dict]:
    """Ultima observacao gravada para ESTA request (payload decodificado)."""
    row = conn.execute(
        "SELECT id, payload, created_at FROM task_events "
        " WHERE kind = ? ORDER BY id DESC LIMIT 200", (PROGRESS_KIND,),
    ).fetchall()
    for item in row:
        payload = kb._json_or(item["payload"], {}) or {}
        if payload.get("request_id") == request_id:
            return {"id": int(item["id"]), "created_at": int(item["created_at"]), **payload}
    return None


def record_progress(
    conn: sqlite3.Connection, *, task_id: str, run_id: Optional[int], request_id: str,
    phase: str, reason_code: str, attempt: Optional[int] = None,
    generation: Optional[str] = None,
) -> bool:
    """Grava UMA observacao, e so quando algo material mudou. ``True`` = gravou.

    Material = etapa, motivo, evidencia mais recente ou numero da tentativa. A
    passagem do relogio NAO e material (ordem do H1 em 1058) e por isso nem
    aparece na comparacao: um worker que faz mil polls na mesma espera escreve
    exatamente uma linha.

    ``expected_next`` vem da tabela :data:`NEXT_ACTION`, nao do chamador: dois
    produtores nao podem divergir sobre o que destrava a mesma causa.

    Abre a propria txn (``allow_nested``) porque os chamadores sao tanto o
    worker (fora de txn) quanto caminhos ja transacionados.
    """
    evidence_id, _ = last_evidence(conn, task_id, run_id)
    previous = _last_progress(conn, request_id)
    if previous is not None and (
            previous.get("phase") == phase
            and previous.get("reason_code") == reason_code
            and previous.get("evidence_event_id") == evidence_id
            and previous.get("attempt") == attempt):
        return False
    with kb.write_txn(conn, allow_nested=True):
        kb._append_event(
            conn, task_id, PROGRESS_KIND,
            {"request_id": request_id, "phase": phase, "reason_code": reason_code,
             "expected_next": NEXT_ACTION.get(reason_code, ""),
             "evidence_event_id": evidence_id, "attempt": attempt,
             "generation": generation},
            run_id=run_id,
        )
    return True


def _notice_retry_marker(conn: sqlite3.Connection, request_id: str) -> int:
    """Id do ultimo ``approval_notice_retry`` desta request (0 se nunca houve).

    O orcamento de tentativas conta a partir dele: um "Retry notice" humano nao
    apaga historia, so move a marca d'agua.
    """
    rows = conn.execute(
        "SELECT id, payload FROM task_events WHERE kind = ? ORDER BY id DESC LIMIT 200",
        (NOTICE_RETRY_KIND,),
    ).fetchall()
    for item in rows:
        payload = kb._json_or(item["payload"], {}) or {}
        if payload.get("request_id") == request_id:
            return int(item["id"])
    return 0


def notice_attempts(conn: sqlite3.Connection, request_id: str, generation: str) -> int:
    """Falhas de entrega ja gravadas para ``(request, geracao)`` apos o ultimo retry.

    Conta EVENTO DURAVEL, nao estado de processo: o dashboard (outro processo)
    precisa ver o mesmo numero que o poller do TUI, e um restart do gateway nao
    pode zerar um orcamento silenciosamente.
    """
    floor = _notice_retry_marker(conn, request_id)
    rows = conn.execute(
        "SELECT id, payload FROM task_events WHERE kind = ? AND id > ? ORDER BY id ASC",
        (PROGRESS_KIND, floor),
    ).fetchall()
    total = 0
    for item in rows:
        payload = kb._json_or(item["payload"], {}) or {}
        if (payload.get("request_id") == request_id
                and payload.get("generation") == generation
                and payload.get("reason_code") == NOTICE_DELIVERY_FAILED):
            total += 1
    return total


def request_notice_retry(
    conn: sqlite3.Connection, *, task_id: str, run_id: Optional[int], request_id: str,
) -> None:
    """Humano pediu nova tentativa de aviso. NAO decide nem reenvia a escrita."""
    with kb.write_txn(conn, allow_nested=True):
        kb._append_event(conn, task_id, NOTICE_RETRY_KIND, {"request_id": request_id},
                         run_id=run_id)


def _delivery_view(conn: sqlite3.Connection, request_id: str) -> dict:
    """Ultimo estado de entrega do aviso desta request.

    ``Transport acknowledged`` -- nunca ``Human read``. Um recibo de transporte
    prova que o frame saiu, nao que alguem leu.
    """
    floor = _notice_retry_marker(conn, request_id)
    rows = conn.execute(
        "SELECT id, payload FROM task_events WHERE kind = ? AND id > ? ORDER BY id ASC",
        (PROGRESS_KIND, floor),
    ).fetchall()
    status, attempts, generation = "unknown", 0, None
    for item in rows:
        payload = kb._json_or(item["payload"], {}) or {}
        if payload.get("request_id") != request_id or payload.get("phase") != NOTICE:
            continue
        reason = payload.get("reason_code")
        generation = payload.get("generation")
        if reason == NOTICE_DELIVERY_FAILED:
            attempts += 1
            status = "failed"
        elif reason == NOTICE_BUDGET_EXHAUSTED:
            status = "exhausted"
        elif reason == NOTICE_DELIVERED:
            attempts += 1
            status = "delivered"
    label = {"delivered": "Transport acknowledged", "failed": "Delivery failed",
             "exhausted": "Delivery failed; budget exhausted",
             "unknown": "Not observed"}[status]
    return {"delivery_status": status, "delivery_label": label,
            "delivery_attempts": attempts, "delivery_generation": generation}


def _state_view(request: journal.ApprovalRequest, progress: Optional[dict]) -> tuple[str, str]:
    """``(phase, reason_code)`` derivados do ESTADO, corrigidos pela observacao.

    O estado do journal e a verdade; a observacao so refina o motivo quando ela
    existe. ``granted`` sem observacao NAO vira "capacidade cheia" -- vira
    "ainda nao observado", que e o que de fato se sabe.
    """
    if request.state == journal.PENDING:
        return AWAITING_HUMAN, HUMAN_DECISION_PENDING
    if request.state == journal.GRANTED:
        reason = (progress or {}).get("reason_code")
        if reason in ADMISSION_REASONS:
            return AWAITING_ADMISSION, reason
        return AWAITING_ADMISSION, RESUME_REASON_NOT_YET_OBSERVED
    if request.state == journal.CONSUMED:
        if request.applied_at is not None:
            return APPLIED, WRITE_VERIFIED
        return WRITE_RECEIPT_PENDING, APPLICATION_OUTCOME_NOT_CONFIRMED
    return CLOSED, DECISION_CLOSED


def project(conn: sqlite3.Connection, request: journal.ApprovalRequest) -> dict:
    """Projecao de diagnostico para a UI. Separada do payload IMUTAVEL.

    Nada aqui entra em ``approval_requests``: o payload e o hash que o humano
    aprova continuam byte a byte os mesmos. Isto e leitura derivada, e some
    sem consequencia.

    ``resource_cost`` sai ``None`` de proposito: CPU/I/O da espera nao e medido
    em producao, e a UI mostra ``Unavailable``. Zero seria mentira confortavel.
    """
    progress = _last_progress(conn, request.request_id)
    # Observacao de etapa (ignora as linhas de entrega de aviso, que tem
    # ciclo proprio e nao descrevem a etapa da operacao).
    phase_progress = progress if (progress or {}).get("phase") != NOTICE else None
    if phase_progress is None:
        rows = conn.execute(
            "SELECT id, payload, created_at FROM task_events WHERE kind = ? "
            " ORDER BY id DESC LIMIT 200", (PROGRESS_KIND,)).fetchall()
        for item in rows:
            payload = kb._json_or(item["payload"], {}) or {}
            if payload.get("request_id") == request.request_id and payload.get("phase") != NOTICE:
                phase_progress = {"id": int(item["id"]),
                                  "created_at": int(item["created_at"]), **payload}
                break
    phase, reason = _state_view(request, phase_progress)
    _, evidence_at = last_evidence(conn, request.task_id, request.run_id)
    transition_at = (phase_progress or {}).get("created_at")
    if transition_at is None:
        transition_at = request.decided_at or request.created_at
    return {
        "phase": phase,
        "phase_label": PHASE_LABEL.get(phase, phase),
        "reason": reason,
        "next_action": NEXT_ACTION.get(reason, ""),
        "last_transition_at": int(transition_at),
        "last_evidence_at": evidence_at,
        # Nao medido em producao: a UI mostra "Unavailable", nunca 0.
        "resource_cost": None,
        **_delivery_view(conn, request.request_id),
    }


def record_notice_outcome(
    conn: sqlite3.Connection, *, task_id: str, run_id: Optional[int], request_id: str,
    generation: str, delivered: bool, limit: Optional[int] = None,
) -> str:
    """Registra o desfecho de UMA tentativa de aviso e devolve o status resultante.

    ``delivered`` -> ``delivered``. Falha -> ``failed`` enquanto houver orcamento
    e ``exhausted`` quando ele acaba. Esgotar NAO cancela o pedido, nao decide e
    nao redespacha a escrita: apenas para de bater na mesma porta ate uma
    reconexao real (geracao nova) ou um ``Retry notice`` humano.
    """
    cap = resolve_notice_max_attempts() if limit is None else limit
    if delivered:
        record_progress(conn, task_id=task_id, run_id=run_id, request_id=request_id,
                        phase=NOTICE, reason_code=NOTICE_DELIVERED,
                        attempt=notice_attempts(conn, request_id, generation) + 1,
                        generation=generation)
        return "delivered"
    attempts = notice_attempts(conn, request_id, generation) + 1
    record_progress(conn, task_id=task_id, run_id=run_id, request_id=request_id,
                    phase=NOTICE, reason_code=NOTICE_DELIVERY_FAILED,
                    attempt=attempts, generation=generation)
    if attempts >= cap:
        record_progress(conn, task_id=task_id, run_id=run_id, request_id=request_id,
                        phase=NOTICE, reason_code=NOTICE_BUDGET_EXHAUSTED,
                        attempt=attempts, generation=generation)
        return "exhausted"
    return "failed"


def notice_budget_open(
    conn: sqlite3.Connection, request_id: str, generation: str, limit: Optional[int] = None,
) -> bool:
    """Ainda ha tentativa de aviso disponivel para ``(request, geracao)``?"""
    cap = resolve_notice_max_attempts() if limit is None else limit
    return notice_attempts(conn, request_id, generation) < cap


def transport_generation(transport: Any) -> str:
    """Assinatura estavel da CONEXAO que entrega o aviso.

    Carimbada no proprio objeto de transporte: uma reconexao real troca o objeto
    e ganha orcamento novo por construcao, sem depender de ``id()`` (que o
    coletor pode reciclar e faria um orcamento velho travar uma conexao nova).
    Transporte que nao aceita atributo cai num rotulo generico -- honesto, so
    menos granular.
    """
    import uuid
    if transport is None:
        return "none"
    existing = getattr(transport, "_hermes_approval_generation", None)
    if existing:
        return str(existing)
    token = uuid.uuid4().hex[:12]
    try:
        setattr(transport, "_hermes_approval_generation", token)
    except (AttributeError, TypeError):
        return f"{type(transport).__name__}:unstamped"
    return token
