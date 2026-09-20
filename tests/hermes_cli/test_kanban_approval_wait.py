"""Espera humana de aprovação: journal, estado ``waiting_approval`` e retomada.

Implementação das etapas 1-2 do contrato
``docs/evidencia/t_78aaa333/contrato-aprovacao-humana-v3.md``. Cada teste afirma um
CONTRATO entre duas peças (a pausa contra as varreduras de reciclagem, o CAS de
retomada contra ``reconcile_orphaned_running``, o predicado de órfã contra o DDL) —
nunca um valor congelado.

Todo teste com uma guarda carrega o controle positivo da mesma guarda na mesma
execução: uma trava que recusa tudo não prova nada.
"""

from __future__ import annotations

import os
import sqlite3
import time

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_approvals as appr
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as disp


@pytest.fixture()
def conn(tmp_path):
    db = kb.init_db(db_path=tmp_path / "kanban.db")
    c = kbc.connect(db)
    yield c
    c.close()


def _task(conn, **kw) -> str:
    return kb.create_task(
        conn, title=kw.pop("title", "t"), assignee=kw.pop("assignee", "executor"), **kw)


def _running(conn, **kw) -> tuple[str, int]:
    """Task reivindicada, com o run aberto: o estado do qual a pausa parte."""
    tid = _task(conn, **kw)
    kb.recompute_ready(conn)
    assert kb.claim_task(conn, tid) is not None
    run_id = kb.get_task(conn, tid).current_run_id
    assert run_id is not None
    return tid, int(run_id)


def _payload(path: str = "/tmp/AGENTS.md") -> dict:
    return {"op": "write_file", "reasons": ["AGENTS.md"],
            "targets": [{"path_input": path, "path_real": path, "is_symlink": False,
                         "symlink_to": None, "pre_sha256": None, "pre_size": None,
                         "post_sha256": "f" * 64, "post_size": 3, "post_blob": "abc",
                         "diff_unified": "+abc"}]}


def _create(conn, tid: str, run_id: int, *, payload=None, **kw) -> appr.ApprovalRequest:
    with kb.write_txn(conn):
        return appr.create_request(
            conn, task_id=tid, run_id=run_id,
            claim_lock=kw.pop("claim_lock", kb._claimer_id()),
            profile_home=kw.pop("profile_home", "/tmp/home"),
            session_key=kw.pop("session_key", "sess"),
            workspace_path=kw.pop("workspace_path", "/tmp/ws"),
            created_by_pid=kw.pop("created_by_pid", os.getpid()),
            created_by_started_at=kw.pop("created_by_started_at", "epoch|1"),
            payload=payload if payload is not None else _payload(), **kw)


# ---------------------------------------------------------------------------
# Journal (contrato §2, §3.4)
# ---------------------------------------------------------------------------


def test_migration_creates_journal_on_a_legacy_board(tmp_path):
    """Board sem a tabela continua abrindo e ganha o journal (M-1/M-2).

    Controle positivo da mesma medição: as tasks pré-existentes continuam legíveis,
    então a migração é aditiva e não reescreveu linha nenhuma.
    """
    db_path = tmp_path / "legacy.db"
    seed = sqlite3.connect(db_path)
    seed.execute(
        "CREATE TABLE tasks (id TEXT PRIMARY KEY, title TEXT NOT NULL,"
        " status TEXT NOT NULL, created_at INTEGER NOT NULL)")
    seed.execute("INSERT INTO tasks VALUES ('t_old', 'antiga', 'todo', 1)")
    seed.commit()
    seed.close()

    conn = kbc.connect(db_path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "approval_requests" in tables
        assert [t.id for t in kb.list_tasks(conn)] == ["t_old"]
    finally:
        conn.close()


def test_journal_ddl_matches_the_dataclass_field_by_field(conn):
    """A lista de §2.1 e o DDL de §3.4 são a MESMA lista.

    Divergir aqui foi o bloqueador R1 #2: um campo que existe num lado e não no outro
    vira NULL silencioso em quem lê.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(approval_requests)")}
    fields = set(appr.ApprovalRequest.__dataclass_fields__)
    assert cols == fields, f"DDL e dataclass divergem: {cols ^ fields}"


def test_only_one_pending_request_per_run(conn):
    """U-3 é constraint do banco, não prosa: a segunda pendência é recusada.

    Sem isso, duas filas humanas coexistem para o mesmo run e o contador do board mente.
    """
    tid, run_id = _running(conn)
    _create(conn, tid, run_id)
    with pytest.raises(appr.ApprovalPendingExists):
        _create(conn, tid, run_id, payload=_payload("/tmp/SOUL.md"))

    # Controles POSITIVOS: outro run pode; e decidir a primeira libera nova pendência.
    _create(conn, tid, run_id + 1)
    with kb.write_txn(conn):
        assert appr.decide_request(
            conn, appr.pending_for_run(conn, tid, run_id).request_id,
            decision=appr.DENIED, decided_by="h1", decision_surface="desktop")
    _create(conn, tid, run_id)
    assert appr.count_pending(conn) == 2


def test_request_hash_is_canonical_and_content_sensitive(conn):
    """P-5: o hash é estável à ordem das chaves e muda com o conteúdo.

    A UI exibe o hash e a decisão humana o ecoa; se ele dependesse da ordem de
    serialização, a decisão seria recusada por divergência inventada.
    """
    a = {"op": "write_file", "targets": [{"path_real": "/x", "post_sha256": "a" * 64}]}
    b = {"targets": [{"post_sha256": "a" * 64, "path_real": "/x"}], "op": "write_file"}
    assert appr.request_hash(a) == appr.request_hash(b)

    c = {"op": "write_file", "targets": [{"path_real": "/x", "post_sha256": "b" * 64}]}
    assert appr.request_hash(c) != appr.request_hash(a)

    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id, payload=a)
    assert req.request_hash == appr.request_hash(a)
    assert req.payload == a


def test_consume_is_single_use_and_only_from_granted(conn):
    """4.1: o CAS de consumo autoriza uma vez só, e só uma decisão concedida.

    Duplo clique, replay e dois consumidores concorrentes perdem todos menos um.
    """
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)

    # Pendente ainda não autoriza — o consumo só olha ``granted``.
    assert appr.consume_grant(conn, req.request_id) is False

    with kb.write_txn(conn):
        assert appr.decide_request(
            conn, req.request_id, decision=appr.GRANTED,
            decided_by="h1", decision_surface="desktop")
    assert appr.consume_grant(conn, req.request_id) is True    # controle POSITIVO
    assert appr.consume_grant(conn, req.request_id) is False   # segundo clique
    assert appr.get_request(conn, req.request_id).state == appr.CONSUMED


def test_decision_refuses_a_hash_that_no_longer_matches(conn):
    """U-7: o clique alcança apenas a alteração exibida.

    Um ``request_hash`` divergente significa que a preimagem mudou desde o que o
    humano viu — aprovar aí seria aprovar outra coisa.
    """
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    assert appr.decide_request(
        conn, req.request_id, decision=appr.GRANTED, decided_by="h1",
        decision_surface="desktop", expected_hash="0" * 64) is False
    assert appr.get_request(conn, req.request_id).state == appr.PENDING

    # Controle POSITIVO: com o hash certo, a mesma chamada decide.
    assert appr.decide_request(
        conn, req.request_id, decision=appr.GRANTED, decided_by="h1",
        decision_surface="desktop", expected_hash=req.request_hash) is True


def test_terminal_states_are_not_decidable_again(conn):
    """U-7: um clique atrasado numa decisão encerrada não cria segunda autorização."""
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    with kb.write_txn(conn):
        assert appr.decide_request(
            conn, req.request_id, decision=appr.DENIED,
            decided_by="h1", decision_surface="desktop")
    assert appr.decide_request(
        conn, req.request_id, decision=appr.GRANTED,
        decided_by="h1", decision_surface="desktop") is False
    assert appr.get_request(conn, req.request_id).state == appr.DENIED


def test_orphan_predicate_covers_every_unapplied_state(conn):
    """R-7: um predicado, um destino — ``consumed`` não-aplicada inclusive.

    Era o bloqueador R2 #2: uma request consumida cujo worker morreu antes de
    escrever não era vista por ninguém e o card ficava preso para sempre.
    """
    tid, run_id = _running(conn)
    pend = _create(conn, tid, run_id, payload=_payload("/a"))
    grant = _create(conn, tid, run_id + 1, payload=_payload("/b"))
    cons = _create(conn, tid, run_id + 2, payload=_payload("/c"))
    applied = _create(conn, tid, run_id + 3, payload=_payload("/d"))
    denied = _create(conn, tid, run_id + 4, payload=_payload("/e"))

    with kb.write_txn(conn):
        for r in (grant, cons, applied):
            appr.decide_request(conn, r.request_id, decision=appr.GRANTED,
                                decided_by="h1", decision_surface="desktop")
        appr.decide_request(conn, denied.request_id, decision=appr.DENIED,
                            decided_by="h1", decision_surface="desktop")
        appr.consume_grant(conn, cons.request_id)
        appr.consume_grant(conn, applied.request_id)
        assert appr.mark_applied(conn, applied.request_id) is True

    orfas = {r.request_id for r in appr.unapplied_requests(conn)}
    assert orfas == {pend.request_id, grant.request_id, cons.request_id}
    assert applied.request_id not in orfas, "a operação aplicada voltou à varredura"
    assert denied.request_id not in orfas, "um terminal humano entrou na varredura"


def test_applied_receipt_only_stamps_a_consumed_request_once(conn):
    """4.2 passo 7: o recibo de escrita é único e exige consumo prévio."""
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    assert appr.mark_applied(conn, req.request_id) is False  # ainda pendente

    with kb.write_txn(conn):
        appr.decide_request(conn, req.request_id, decision=appr.GRANTED,
                            decided_by="h1", decision_surface="desktop")
        appr.consume_grant(conn, req.request_id)
    assert appr.mark_applied(conn, req.request_id) is True   # controle POSITIVO
    assert appr.mark_applied(conn, req.request_id) is False  # não recarimba


def test_granted_for_run_matches_only_the_same_operation(conn):
    """R-4: um gesto humano por operação; outra operação exige novo pedido."""
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    with kb.write_txn(conn):
        appr.decide_request(conn, req.request_id, decision=appr.GRANTED,
                            decided_by="h1", decision_surface="desktop")

    achado = appr.granted_for_run(conn, tid, run_id, req.request_hash)
    assert achado is not None and achado.request_id == req.request_id
    assert appr.granted_for_run(conn, tid, run_id, "0" * 64) is None

    # Consumida deixa de servir: a autorização é de uso único.
    appr.consume_grant(conn, req.request_id)
    assert appr.granted_for_run(conn, tid, run_id, req.request_hash) is None


# ---------------------------------------------------------------------------
# Estado e transições (contrato §3.2)
# ---------------------------------------------------------------------------


def test_waiting_approval_is_valid_but_never_initial(conn):
    """E-1: nenhum card nasce esperando aprovação.

    O estado é válido para o board, mas o construtor não o aceita: chegar nele é
    privilégio de ``pause_for_approval``, a partir de ``running``.
    """
    assert "waiting_approval" in kb.VALID_STATUSES
    assert "waiting_approval" not in kb.VALID_INITIAL_STATUSES

    with pytest.raises(ValueError):
        kb.create_task(conn, title="t", assignee="executor",
                       initial_status="waiting_approval")

    # Controle POSITIVO: os estados iniciais legítimos continuam passando.
    assert kb.create_task(conn, title="t", assignee="executor", initial_status="blocked")


def test_pause_releases_claim_and_slot_without_ending_the_run(conn):
    """E-3/E-3.1: a espera solta claim e vaga, mas NÃO encerra o run.

    Encerrar o run habilitaria ``reap_terminal_workers``, que mataria em 2 min o
    próprio processo que espera a decisão.
    """
    tid, run_id = _running(conn)
    assert disp.count_running_tasks(conn) == 1
    req = _create(conn, tid, run_id)

    assert kb.pause_for_approval(
        conn, tid, request_id=req.request_id, request_hash=req.request_hash,
        expected_run_id=run_id, targets=["/tmp/AGENTS.md"]) is True

    t = kb.get_task(conn, tid)
    assert t.status == "waiting_approval"
    assert t.claim_lock is None and t.worker_pid is None
    assert t.current_run_id == run_id, "o run foi encerrado — E-3.1 violado"
    assert disp.count_running_tasks(conn) == 0, "a espera humana ocupou vaga do orçamento"
    assert conn.execute(
        "SELECT ended_at FROM task_runs WHERE id = ?", (run_id,)).fetchone()[0] is None


def test_pause_does_not_count_a_failure_or_a_block_recurrence(conn):
    """E-3: demora humana não é falha — nada de ``triage`` por esperar."""
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    kb.pause_for_approval(conn, tid, request_id=req.request_id,
                          request_hash=req.request_hash, expected_run_id=run_id)
    row = conn.execute(
        "SELECT consecutive_failures, block_kind, block_recurrences FROM tasks WHERE id=?",
        (tid,)).fetchone()
    assert row["consecutive_failures"] == 0
    assert row["block_kind"] is None and row["block_recurrences"] == 0


def test_pause_refuses_a_stale_run_id(conn):
    """E-3 CAS: a pausa pertence ao run vigente; um run velho não pausa o card."""
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    assert kb.pause_for_approval(
        conn, tid, request_id=req.request_id, request_hash=req.request_hash,
        expected_run_id=run_id + 999) is False
    assert kb.get_task(conn, tid).status == "running"

    # Controle POSITIVO: com o run certo, a mesma chamada pausa.
    assert kb.pause_for_approval(
        conn, tid, request_id=req.request_id, request_hash=req.request_hash,
        expected_run_id=run_id) is True


def test_the_five_recycling_sweeps_leave_a_paused_card_alone(conn):
    """E-7: as CINCO varreduras de reciclagem só alcançam ``running``.

    Se qualquer uma delas pegasse ``waiting_approval``, a demora humana viraria
    respawn com LLM — que é a regeneração proibida por R-3. Controle POSITIVO na
    mesma execução: uma task realmente ``running`` e vencida É reciclada.
    """
    parado, run_id = _running(conn, max_runtime_seconds=1)
    req = _create(conn, parado, run_id)
    kb.pause_for_approval(conn, parado, request_id=req.request_id,
                          request_hash=req.request_hash, expected_run_id=run_id)

    vivo, vivo_run = _running(conn)
    conn.execute(
        "UPDATE tasks SET claim_expires = 1, started_at = 1, last_heartbeat_at = NULL, "
        "worker_pid = NULL WHERE id=?", (vivo,))
    conn.execute("UPDATE task_runs SET started_at = 1 WHERE id = ?", (vivo_run,))
    conn.commit()

    disp.detect_stale_running(conn, stale_timeout_seconds=1)
    disp.reconcile_orphaned_running(conn)
    disp.detect_crashed_workers(conn)
    disp.enforce_max_runtime(conn)
    kb.release_stale_claims(conn)

    assert kb.get_task(conn, parado).status == "waiting_approval", (
        "uma varredura de reciclagem moveu uma espera humana")
    assert kb.get_task(conn, vivo).status != "running", (
        "nenhuma varredura reciclou o controle positivo — o teste não mediu nada")


def test_recompute_ready_never_promotes_a_paused_card(conn):
    """E-5: promover aqui criaria o respawn-loop que o H1 proibiu."""
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    kb.pause_for_approval(conn, tid, request_id=req.request_id,
                          request_hash=req.request_hash, expected_run_id=run_id)

    kb.recompute_ready(conn)
    assert kb.get_task(conn, tid).status == "waiting_approval"

    # Controle POSITIVO: a mesma varredura promove um 'todo' sem pai pendente.
    outro = _task(conn)
    kb.recompute_ready(conn)
    assert kb.get_task(conn, outro).status == "ready"


def test_a_paused_card_is_not_claimable(conn):
    """E-6: nenhum caminho novo de claim — ``waiting_approval`` não é reclamável."""
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    kb.pause_for_approval(conn, tid, request_id=req.request_id,
                          request_hash=req.request_hash, expected_run_id=run_id)
    assert kb.claim_task(conn, tid) is None
    assert kb.claim_review_task(conn, tid) is None
    assert kb.get_task(conn, tid).status == "waiting_approval"


def test_unblock_task_is_not_a_door_out_of_the_wait(conn):
    """E-8: ``unblock_task`` só aceita ``blocked``/``scheduled``, e continua assim."""
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    kb.pause_for_approval(conn, tid, request_id=req.request_id,
                          request_hash=req.request_hash, expected_run_id=run_id)
    assert kb.unblock_task(conn, tid) is False
    assert kb.get_task(conn, tid).status == "waiting_approval"


# ---------------------------------------------------------------------------
# Retomada (contrato §3.2 E-9) — o bloqueador R2 #1
# ---------------------------------------------------------------------------


def test_resume_restores_identity_in_the_same_cas(conn):
    """E-9: a volta a ``running`` traz claim, PID e fingerprint no MESMO UPDATE.

    Controle POSITIVO do perigo, na mesma execução: a forma ingênua (só o status)
    É reciclada para ``ready`` por ``reconcile_orphaned_running`` — o que faria o
    dispatcher spawnar um segundo worker LLM ao lado do primeiro, ainda vivo.
    """
    # --- a forma ERRADA, para provar que o perigo é real ---
    errado = _task(conn)
    conn.execute(
        "UPDATE tasks SET status='running', claim_lock=NULL, claim_expires=NULL, "
        "worker_pid=NULL, worker_started_at=NULL, last_heartbeat_at=NULL WHERE id=?",
        (errado,))
    conn.commit()
    disp.reconcile_orphaned_running(conn)
    assert kb.get_task(conn, errado).status == "ready", (
        "controle positivo falhou: running+claim NULL não foi reciclado — a premissa "
        "de E-9 mudou, reavaliar o contrato antes de confiar neste teste")

    # --- a forma EXIGIDA ---
    tid, run_id = _running(conn)
    lock = kb.get_task(conn, tid).claim_lock
    req = _create(conn, tid, run_id, claim_lock=lock, created_by_started_at="epoch|1")
    kb.pause_for_approval(conn, tid, request_id=req.request_id,
                          request_hash=req.request_hash, expected_run_id=run_id)

    assert kb.resume_from_pause(
        conn, tid, request_id=req.request_id, claim_lock=req.claim_lock,
        worker_pid=req.created_by_pid, worker_started_at=req.created_by_started_at,
        expected_run_id=run_id) is True

    t = kb.get_task(conn, tid)
    assert t.status == "running"
    assert t.claim_lock == lock and t.worker_pid == req.created_by_pid
    assert t.claim_expires > int(time.time()), "TTL herdado vencido entregaria a task ao stale"

    disp.reconcile_orphaned_running(conn)
    assert kb.get_task(conn, tid).status == "running", (
        "a varredura de órfãs reciclou uma task retomada com identidade restaurada")


def test_resume_fails_closed_when_the_card_left_the_wait(conn):
    """E-9: CAS perdido = sem escrita. O chamador não pode escrever às cegas."""
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    kb.pause_for_approval(conn, tid, request_id=req.request_id,
                          request_hash=req.request_hash, expected_run_id=run_id)
    # Alguém tirou o card da espera por fora (simula a corrida).
    conn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (tid,))
    conn.commit()

    assert kb.resume_from_pause(
        conn, tid, request_id=req.request_id, claim_lock=req.claim_lock,
        worker_pid=req.created_by_pid, worker_started_at=req.created_by_started_at,
        expected_run_id=run_id) is False
    assert kb.get_task(conn, tid).status == "blocked"


def test_human_wait_does_not_consume_max_runtime(conn):
    """T-3/C-30: o tempo parado esperando o humano não conta para o timeout.

    Sem o desconto, um H1 que demora uma hora vira ``timed_out`` do agente — a
    própria falha que esta feature existe para evitar. Controle POSITIVO na mesma
    execução: sem a espera, o mesmo run estourado É terminado.
    """
    tid, run_id = _running(conn, max_runtime_seconds=60)
    agora = int(time.time())
    # O run começou há 10 min, dos quais 9 min foram espera humana.
    conn.execute(
        "UPDATE task_runs SET started_at = ?, approval_wait_seconds = ? WHERE id = ?",
        (agora - 600, 580, run_id))
    conn.execute("UPDATE tasks SET worker_pid = ? WHERE id = ?", (os.getpid(), tid))
    conn.commit()

    assert disp.enforce_max_runtime(conn, signal_fn=lambda *a, **k: None) == []
    assert kb.get_task(conn, tid).status == "running"

    # Controle POSITIVO: zerando o desconto, o mesmo run estoura.
    conn.execute("UPDATE task_runs SET approval_wait_seconds = 0 WHERE id = ?", (run_id,))
    conn.commit()
    assert disp.enforce_max_runtime(conn, signal_fn=lambda *a, **k: None) == [tid]


def test_resume_closes_the_wait_window_and_accumulates_it(conn):
    """T-3: a janela aberta pela pausa vira segundos acumulados na retomada."""
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    kb.pause_for_approval(conn, tid, request_id=req.request_id,
                          request_hash=req.request_hash, expected_run_id=run_id)
    # Simula 300 s de espera recuando o instante da pausa.
    conn.execute(
        "UPDATE task_runs SET approval_paused_at = approval_paused_at - 300 WHERE id = ?",
        (run_id,))
    conn.commit()

    kb.resume_from_pause(
        conn, tid, request_id=req.request_id, claim_lock=req.claim_lock,
        worker_pid=req.created_by_pid, worker_started_at=req.created_by_started_at,
        expected_run_id=run_id)
    row = conn.execute(
        "SELECT approval_wait_seconds, approval_paused_at FROM task_runs WHERE id = ?",
        (run_id,)).fetchone()
    assert row["approval_wait_seconds"] >= 300
    assert row["approval_paused_at"] is None, "a janela ficou aberta e contaria duas vezes"


# ---------------------------------------------------------------------------
# Saídas sem escrita (contrato §3.2 E-4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("outcome,event", sorted(kb.APPROVAL_EXIT_EVENTS.items()))
def test_every_exit_without_a_write_lands_on_blocked_needs_input(conn, outcome, event):
    """E-4: deny, cancel, obsolescência e órfã param todos em ``blocked``/needs_input.

    Nunca ``ready``: promover aqui respawnaria um worker que regeneraria a operação.
    """
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    kb.pause_for_approval(conn, tid, request_id=req.request_id,
                          request_hash=req.request_hash, expected_run_id=run_id)

    assert kb.end_approval_wait(
        conn, tid, request_id=req.request_id, outcome=outcome, reason="motivo") is True
    t = kb.get_task(conn, tid)
    assert t.status == "blocked"
    assert t.block_kind == "needs_input"
    assert t.current_run_id is None, "o run ficou aberto após um desfecho terminal"
    kinds = [e.kind for e in kb.list_events(conn, tid)]
    assert event in kinds


def test_only_a_human_deny_counts_a_block_recurrence(conn):
    """E-4: deny repetido é sinal humano e escala; órfã/obsolescência não escalam.

    Escalar por uma falha de processo puniria o card por algo que o humano não decidiu.
    """
    def _ciclo(tid, run_id, outcome):
        req = _create(conn, tid, run_id)
        kb.pause_for_approval(conn, tid, request_id=req.request_id,
                              request_hash=req.request_hash, expected_run_id=run_id)
        kb.end_approval_wait(conn, tid, request_id=req.request_id, outcome=outcome)

    negado, run_id = _running(conn)
    _ciclo(negado, run_id, "denied")
    assert kb.get_task(conn, negado).block_recurrences == 1

    orfao, run2 = _running(conn)
    _ciclo(orfao, run2, "orphaned")
    assert kb.get_task(conn, orfao).block_recurrences == 0, (
        "uma órfã (falha de processo) escalou o card como se o humano tivesse negado")


def test_end_approval_wait_refuses_a_card_that_is_not_waiting(conn):
    """E-4 CAS: não é um verbo genérico de status disfarçado."""
    tid, run_id = _running(conn)
    req = _create(conn, tid, run_id)
    assert kb.end_approval_wait(
        conn, tid, request_id=req.request_id, outcome="denied") is False
    assert kb.get_task(conn, tid).status == "running"

    with pytest.raises(ValueError):
        kb.end_approval_wait(conn, tid, request_id=req.request_id, outcome="approved")
