"""Journal de aprovacao humana persistente para operacoes de worker Kanban.

Implementa o contrato ``docs/evidencia/t_78aaa333/contrato-aprovacao-humana-v3.md``,
secoes 2 (identidade/payload), 3.4 (DDL aditivo) e 4.1/4.4 (consumo de uso unico e
predicado unico de orfa).

A tabela vive dentro do ``kanban.db`` do board -- nao ha coluna ``board`` (contrato
secao 2.1: uma coluna de nome seria um segundo indice capaz de divergir do arquivo).

Esta camada e TRANSPORTE E AUDITORIA, nunca fonte de autoridade (contrato A-2): quem
consome revalida a preimagem antes de escrever. Nenhuma funcao aqui concede aprovacao;
``decide_request`` so registra a decisao produzida por uma superficie humana viva.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any
from typing import Iterable
from typing import Optional


# Estados da solicitacao. ``orphaned`` e proprio e NAO se confunde com ``cancelled``
# (contrato R-7.2): cancelado = humano retirou; orfao = o processo morreu.
PENDING = "pending"
GRANTED = "granted"
DENIED = "denied"
CANCELLED = "cancelled"
OBSOLETE = "obsolete"
CONSUMED = "consumed"
ORPHANED = "orphaned"

VALID_APPROVAL_STATES = {PENDING, GRANTED, DENIED, CANCELLED, OBSOLETE, CONSUMED, ORPHANED}

# Estados terminais para a decisao humana: um clique atrasado neles responde "ja
# encerrada" em vez de criar uma segunda autorizacao (contrato U-7).
DECIDABLE_STATES = {PENDING}

# Estados nao-terminais alcancados pela varredura de orfas (contrato R-7): um unico
# predicado cobre os tres, e ``applied_at IS NOT NULL`` tira a linha da varredura.
UNAPPLIED_STATES = (PENDING, GRANTED, CONSUMED)

# Decisoes que o endpoint humano pode registrar.
HUMAN_DECISIONS = {GRANTED, DENIED, CANCELLED}


APPROVALS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS approval_requests (
    request_id            TEXT PRIMARY KEY,
    task_id               TEXT NOT NULL,
    run_id                INTEGER NOT NULL,
    -- claim_lock/created_by_pid/created_by_started_at sao a identidade do worker
    -- gravada ANTES de a pausa zera-la na linha de tasks: e o unico lugar onde ela
    -- sobrevive a espera, e e de la que a retomada a restaura (contrato R-0.3/E-9).
    claim_lock            TEXT NOT NULL,
    profile_home          TEXT NOT NULL,
    session_key           TEXT NOT NULL,
    workspace_path        TEXT NOT NULL,
    created_by_pid        INTEGER NOT NULL,
    created_by_started_at TEXT NOT NULL,
    origin_session        TEXT,
    payload_json          TEXT NOT NULL,
    request_hash          TEXT NOT NULL,
    state                 TEXT NOT NULL,
    decided_at            INTEGER,
    decided_by            TEXT,
    decision_surface      TEXT,
    consumed_at           INTEGER,
    -- Recibo de escrita: NULL = a operacao ainda nao foi aplicada. E o campo que
    -- separa "consumido e escrito" de "consumido e o processo morreu antes de
    -- escrever", que sem ele deixava o card irrecuperavel (contrato R-5.1/R-7).
    applied_at            INTEGER,
    created_at            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appr_task_state ON approval_requests(task_id, state);
CREATE INDEX IF NOT EXISTS idx_appr_state ON approval_requests(state);
-- No maximo UMA pendencia por run: a segunda tentativa falha por IntegrityError em
-- vez de abrir uma segunda fila humana (contrato 2.1 U-3).
CREATE UNIQUE INDEX IF NOT EXISTS idx_appr_one_pending_per_run
  ON approval_requests(task_id, run_id) WHERE state = 'pending';
-- A varredura de orfas percorre exatamente as nao-aplicadas.
CREATE INDEX IF NOT EXISTS idx_appr_unapplied
  ON approval_requests(state) WHERE applied_at IS NULL;
"""


@dataclass
class ApprovalRequest:
    """Uma solicitacao de aprovacao humana. Espelha o DDL campo a campo."""

    request_id: str
    task_id: str
    run_id: int
    claim_lock: str
    profile_home: str
    session_key: str
    workspace_path: str
    created_by_pid: int
    created_by_started_at: str
    payload_json: str
    request_hash: str
    state: str
    created_at: int
    origin_session: Optional[str] = None
    decided_at: Optional[int] = None
    decided_by: Optional[str] = None
    decision_surface: Optional[str] = None
    consumed_at: Optional[int] = None
    applied_at: Optional[int] = None

    @property
    def payload(self) -> dict:
        """Payload desserializado (imutavel apos a criacao -- contrato 2.2)."""
        return json.loads(self.payload_json)


def _row_to_request(row: Any) -> ApprovalRequest:
    return ApprovalRequest(
        request_id=row["request_id"],
        task_id=row["task_id"],
        run_id=int(row["run_id"]),
        claim_lock=row["claim_lock"],
        profile_home=row["profile_home"],
        session_key=row["session_key"],
        workspace_path=row["workspace_path"],
        created_by_pid=int(row["created_by_pid"]),
        created_by_started_at=row["created_by_started_at"],
        payload_json=row["payload_json"],
        request_hash=row["request_hash"],
        state=row["state"],
        created_at=int(row["created_at"]),
        origin_session=row["origin_session"],
        decided_at=row["decided_at"],
        decided_by=row["decided_by"],
        decision_surface=row["decision_surface"],
        consumed_at=row["consumed_at"],
        applied_at=row["applied_at"],
    )


def new_request_id() -> str:
    """Identidade da solicitacao (hex 32), gerada pelo processo do worker."""
    return uuid.uuid4().hex


def canonical_payload_json(payload: dict) -> str:
    """Serializacao canonica: chaves ordenadas, separadores fixos.

    O hash so e comparavel entre processos se as duas pontas serializarem do mesmo
    jeito -- a UI exibe o hash e a decisao humana o ecoa de volta (contrato P-5).
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def request_hash(payload: dict) -> str:
    """sha256 do payload canonico (contrato P-5)."""
    return hashlib.sha256(canonical_payload_json(payload).encode("utf-8")).hexdigest()


class ApprovalPendingExists(Exception):
    """Ja existe uma pendencia para este ``(task_id, run_id)`` (contrato U-3)."""


def create_request(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    run_id: int,
    claim_lock: str,
    profile_home: str,
    session_key: str,
    workspace_path: str,
    created_by_pid: int,
    created_by_started_at: str,
    payload: dict,
    origin_session: Optional[str] = None,
    request_id: Optional[str] = None,
    now: Optional[int] = None,
) -> ApprovalRequest:
    """Cria a solicitacao em ``pending``. O caller detem a txn.

    Levanta :class:`ApprovalPendingExists` quando o indice unico parcial recusa uma
    segunda pendencia para o mesmo run -- o chamador trata como "ja existe pedido",
    nunca como erro de banco a engolir.
    """
    rid = request_id or new_request_id()
    ts = int(now if now is not None else time.time())
    payload_json = canonical_payload_json(payload)
    rhash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    try:
        conn.execute(
            """
            INSERT INTO approval_requests (
                request_id, task_id, run_id, claim_lock, profile_home, session_key,
                workspace_path, created_by_pid, created_by_started_at, origin_session,
                payload_json, request_hash, state, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid, task_id, int(run_id), claim_lock, profile_home, session_key,
                workspace_path, int(created_by_pid), str(created_by_started_at),
                origin_session, payload_json, rhash, PENDING, ts,
            ),
        )
    except sqlite3.IntegrityError as exc:
        # SQLite nomeia as COLUNAS ("UNIQUE constraint failed: approval_requests.task_id,
        # approval_requests.run_id"), nunca o indice parcial -- casar pelo nome do indice
        # nunca dispara. Pergunta-se ao banco qual e o conflito em vez de ler a string.
        if pending_for_run(conn, task_id, int(run_id)) is not None:
            raise ApprovalPendingExists(
                f"task {task_id} run {run_id} already has a pending approval request"
            ) from exc
        raise
    return ApprovalRequest(
        request_id=rid, task_id=task_id, run_id=int(run_id), claim_lock=claim_lock,
        profile_home=profile_home, session_key=session_key, workspace_path=workspace_path,
        created_by_pid=int(created_by_pid), created_by_started_at=str(created_by_started_at),
        payload_json=payload_json, request_hash=rhash, state=PENDING, created_at=ts,
        origin_session=origin_session,
    )


def get_request(conn: sqlite3.Connection, request_id: str) -> Optional[ApprovalRequest]:
    row = conn.execute(
        "SELECT * FROM approval_requests WHERE request_id = ?", (request_id,)
    ).fetchone()
    return _row_to_request(row) if row is not None else None


def list_requests(
    conn: sqlite3.Connection, *, task_id: Optional[str] = None,
    states: Optional[Iterable[str]] = None,
) -> list[ApprovalRequest]:
    """Solicitacoes do board, mais recentes por ultimo."""
    where, params = [], []
    if task_id is not None:
        where.append("task_id = ?")
        params.append(task_id)
    state_list = list(states) if states is not None else None
    if state_list:
        where.append(f"state IN ({','.join('?' * len(state_list))})")
        params.extend(state_list)
    sql = "SELECT * FROM approval_requests"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at ASC, rowid ASC"
    return [_row_to_request(r) for r in conn.execute(sql, params)]


def count_pending(conn: sqlite3.Connection) -> int:
    """Contador do topo do board (contrato U-3): conta REQUESTS pendentes, nunca
    cards -- um card pode ter varias requests ao longo do tempo."""
    return int(conn.execute(
        "SELECT COUNT(*) FROM approval_requests WHERE state = ?", (PENDING,)
    ).fetchone()[0])


def pending_for_run(
    conn: sqlite3.Connection, task_id: str, run_id: int,
) -> Optional[ApprovalRequest]:
    row = conn.execute(
        "SELECT * FROM approval_requests WHERE task_id = ? AND run_id = ? AND state = ?",
        (task_id, int(run_id), PENDING),
    ).fetchone()
    return _row_to_request(row) if row is not None else None


def granted_for_run(
    conn: sqlite3.Connection, task_id: str, run_id: int, request_hash_value: str,
) -> Optional[ApprovalRequest]:
    """Decisao ``granted`` ainda nao consumida para ESTA operacao exata.

    E o que permite um unico gesto humano (contrato R-4): ao retomar, a guarda
    encontra a decisao pelo mesmo ``request_hash`` e consome em vez de abrir um
    segundo pedido. Hash diferente e outra operacao, e um novo pedido e legitimo.
    """
    row = conn.execute(
        "SELECT * FROM approval_requests "
        " WHERE task_id = ? AND run_id = ? AND request_hash = ? "
        "   AND state = ? AND consumed_at IS NULL",
        (task_id, int(run_id), request_hash_value, GRANTED),
    ).fetchone()
    return _row_to_request(row) if row is not None else None


def decide_request(
    conn: sqlite3.Connection, request_id: str, *, decision: str,
    decided_by: str, decision_surface: str, expected_hash: Optional[str] = None,
    now: Optional[int] = None,
) -> bool:
    """Registra a decisao humana. ``False`` quando o CAS perde (ja decidida).

    ``decided_by`` e a identidade HUMANA e a superficie, nunca um perfil de agente
    (contrato U-7). ``expected_hash`` recusa um clique sobre uma preimagem que mudou
    desde o que o humano viu: aprovar o que esta na tela, nao o que esta no banco.
    """
    if decision not in HUMAN_DECISIONS:
        raise ValueError(f"decision must be one of {sorted(HUMAN_DECISIONS)}, got {decision!r}")
    ts = int(now if now is not None else time.time())
    sql = (
        "UPDATE approval_requests "
        "   SET state = ?, decided_at = ?, decided_by = ?, decision_surface = ? "
        " WHERE request_id = ? AND state = ?"
    )
    params: tuple = (decision, ts, decided_by, decision_surface, request_id, PENDING)
    if expected_hash is not None:
        sql += " AND request_hash = ?"
        params = (*params, expected_hash)
    return conn.execute(sql, params).rowcount == 1


def consume_grant(
    conn: sqlite3.Connection, request_id: str, *, now: Optional[int] = None,
) -> bool:
    """CAS de consumo de uso unico (contrato 4.1). ``False`` = nao autoriza.

    Duplo clique, replay e dois consumidores concorrentes perdem todos menos um. Uma
    decisao ``denied``/``cancelled``/``obsolete`` nunca passa por aqui, e ``consumed``
    NAO volta a ``granted`` -- reabrir a decisao seria exatamente o replay que o uso
    unico existe para impedir.
    """
    ts = int(now if now is not None else time.time())
    return conn.execute(
        "UPDATE approval_requests SET state = ?, consumed_at = ? "
        " WHERE request_id = ? AND state = ? AND consumed_at IS NULL",
        (CONSUMED, ts, request_id, GRANTED),
    ).rowcount == 1


def mark_applied(
    conn: sqlite3.Connection, request_id: str, *, now: Optional[int] = None,
) -> bool:
    """Carimba o recibo de escrita (contrato 4.2 passo 7).

    A partir daqui a operacao esta aplicada e a request e terminal-feliz; antes dele
    ela e uma decisao nao aplicada e a varredura de orfas a alcanca. So carimba uma
    vez, e so sobre uma request consumida.
    """
    ts = int(now if now is not None else time.time())
    return conn.execute(
        "UPDATE approval_requests SET applied_at = ? "
        " WHERE request_id = ? AND state = ? AND applied_at IS NULL",
        (ts, request_id, CONSUMED),
    ).rowcount == 1


def mark_obsolete(
    conn: sqlite3.Connection, request_id: str, *, now: Optional[int] = None,
) -> bool:
    """Revalidacao reprovou (preimagem/symlink mudaram): a operacao nao escreve.

    Vale para uma request ainda pendente/concedida e tambem para uma ja consumida --
    o consumo acontece DENTRO da regiao critica, antes da revalidacao, entao o caminho
    "consumiu e a preimagem nao batia" precisa de um destino honesto e terminal.
    """
    ts = int(now if now is not None else time.time())
    return conn.execute(
        "UPDATE approval_requests SET state = ?, decided_at = COALESCE(decided_at, ?) "
        " WHERE request_id = ? AND state IN (?, ?, ?) AND applied_at IS NULL",
        (OBSOLETE, ts, request_id, PENDING, GRANTED, CONSUMED),
    ).rowcount == 1


def mark_orphaned(
    conn: sqlite3.Connection, request_id: str, *, now: Optional[int] = None,
) -> bool:
    """A criadora morreu sem aplicar a operacao (contrato R-7)."""
    ts = int(now if now is not None else time.time())
    placeholders = ",".join("?" * len(UNAPPLIED_STATES))
    return conn.execute(
        f"UPDATE approval_requests SET state = ?, decided_at = COALESCE(decided_at, ?) "
        f" WHERE request_id = ? AND applied_at IS NULL AND state IN ({placeholders})",
        (ORPHANED, ts, request_id, *UNAPPLIED_STATES),
    ).rowcount == 1


def unapplied_requests(conn: sqlite3.Connection) -> list[ApprovalRequest]:
    """O predicado UNICO da varredura de orfas (contrato R-7).

    ``applied_at IS NULL AND state IN ('pending','granted','consumed')``. A request
    aplicada sai da varredura: a operacao aconteceu, e um crash depois disso e
    problema do worker, nao da autorizacao. O cruzamento com "o criador nao esta mais
    vivo" fica no dispatcher, que e quem sabe medir liveness de PID.
    """
    placeholders = ",".join("?" * len(UNAPPLIED_STATES))
    rows = conn.execute(
        f"SELECT * FROM approval_requests "
        f" WHERE applied_at IS NULL AND state IN ({placeholders}) "
        f" ORDER BY created_at ASC, rowid ASC",
        UNAPPLIED_STATES,
    ).fetchall()
    return [_row_to_request(r) for r in rows]
