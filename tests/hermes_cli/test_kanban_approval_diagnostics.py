"""Diagnóstico contextual da espera de aprovação (card t_78aaa333, 1057/1058).

Contratos exercitados aqui, todos com controle negativo no mesmo arquivo:

- observação não nasce do relógio, só de mudança material (1058);
- o motivo da recusa de admissão vem da MESMA avaliação sob o lock, não de um
  palpite posterior;
- o orçamento de aviso é durável e por geração de transporte, e esgotá-lo não
  decide, não cancela e não redespacha a escrita;
- ``approval_progress`` não é kind de notificação: diagnóstico não acorda modelo.
"""
import time

import pytest

from hermes_cli import kanban_approval_diagnostics as diag
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_approvals as journal
from hermes_cli.kanban_db_connect import connect


@pytest.fixture
def board(tmp_path):
    db = kb.init_db(db_path=tmp_path / "board.db")
    conn = connect(db)
    yield conn
    conn.close()


def _events(conn, kind=diag.PROGRESS_KIND):
    return conn.execute("SELECT payload FROM task_events WHERE kind = ? ORDER BY id",
                        (kind,)).fetchall()


def _task(conn, **kw):
    tid = kb.create_task(conn, title="diag fixture", assignee="fixture", **kw)
    kb.recompute_ready(conn)
    return tid, kb.claim_task(conn, tid)


def test_repeated_polls_on_an_unchanged_wait_write_one_observation(board):
    """Poll repetido é silencioso; evidência nova quebra o silêncio.

    É o contrato que o H1 pediu em 1058: passagem do relógio não caracteriza
    defeito nem gera linha. Controle negativo na segunda metade — se a
    deduplicação fosse por tempo em vez de por conteúdo, o evento novo abaixo
    não apareceria.
    """
    tid, task = _task(board)
    for _ in range(5):
        diag.record_progress(board, task_id=tid, run_id=task.current_run_id,
                             request_id="ap_x", phase=diag.AWAITING_HUMAN,
                             reason_code=diag.HUMAN_DECISION_PENDING)
        time.sleep(0.01)
    assert len(_events(board)) == 1

    # Evidência material nova (um evento real do run) volta a produzir linha.
    kb.add_comment(board, tid, author="fixture", body="something happened")
    assert diag.record_progress(board, task_id=tid, run_id=task.current_run_id,
                                request_id="ap_x", phase=diag.AWAITING_HUMAN,
                                reason_code=diag.HUMAN_DECISION_PENDING) is True
    assert len(_events(board)) == 2


def test_each_material_change_produces_exactly_one_new_observation(board):
    """Etapa, motivo e tentativa são critérios independentes de gravação.

    Sem um deles a espera fica cega para a transição correspondente: mudar de
    'esperando humano' para 'esperando vaga' sem gravar nada deixaria o painel
    mostrando a etapa anterior para sempre. Os três são exercitados isolados —
    só um campo muda por passo, então cada assert acusa um critério só.
    """
    tid, task = _task(board)
    step = lambda **kw: diag.record_progress(  # noqa: E731 - tabela de passos
        board, task_id=tid, run_id=task.current_run_id, request_id="ap_s", **kw)

    base = dict(phase=diag.AWAITING_HUMAN, reason_code=diag.HUMAN_DECISION_PENDING)
    assert step(**base) is True
    assert step(**base) is False, "poll idêntico não pode gravar"

    # Só a ETAPA muda.
    assert step(**{**base, "phase": diag.AWAITING_ADMISSION}) is True
    # Só o MOTIVO muda.
    assert step(phase=diag.AWAITING_ADMISSION, reason_code=diag.HOST_CAPACITY) is True
    # Só a TENTATIVA muda.
    assert step(phase=diag.AWAITING_ADMISSION, reason_code=diag.HOST_CAPACITY,
                attempt=1) is True
    assert step(phase=diag.AWAITING_ADMISSION, reason_code=diag.HOST_CAPACITY,
                attempt=1) is False
    assert len(_events(board)) == 4


def test_progress_events_never_reach_a_notification_or_wake_path():
    """Diagnóstico é para o painel, não para o modelo.

    Se ``approval_progress`` entrasse em qualquer uma dessas listas, cada poll
    do worker viraria mensagem — e o kind é gravado a cada mudança de etapa.
    """
    from gateway import kanban_watchers_notifier as notifier
    from tui_gateway import session_notifications as notif
    assert diag.PROGRESS_KIND not in notifier.TERMINAL_KINDS
    assert diag.PROGRESS_KIND not in notifier._WAKE_KINDS
    assert diag.PROGRESS_KIND not in notif._KANBAN_NOTIFY_KINDS
    assert diag.NOTICE_RETRY_KIND not in notif._KANBAN_NOTIFY_KINDS


def test_every_reason_code_carries_an_action_the_operator_can_take():
    """Nenhum motivo pode chegar à UI sem resposta para 'e agora?'.

    Contrato entre duas peças de dados (motivos × ações), não retrato de texto.
    """
    reasons = {value for name, value in vars(diag).items()
               if name.isupper() and isinstance(value, str) and name not in {
                   "PROGRESS_KIND", "NOTICE_RETRY_KIND", "AWAITING_HUMAN",
                   "AWAITING_ADMISSION", "APPLYING", "APPLIED",
                   "WRITE_RECEIPT_PENDING", "CLOSED", "NOTICE"}}
    assert reasons, "sanity: reason codes must be discoverable"
    for reason in reasons:
        assert diag.NEXT_ACTION.get(reason), f"reason {reason} has no next action"


def test_granted_without_an_observation_reports_not_yet_observed(tmp_path, monkeypatch):
    """``granted`` parado sem observação NÃO vira 'capacidade cheia'.

    Adivinhar a causa mais provável seria exatamente a mentira confortável: a
    projeção diz o que sabe.
    """
    import os

    from hermes_cli.kanban_approval_lifecycle import record_human_decision
    from hermes_cli.kanban_db_dispatch import _set_worker_pid
    from tools import file_approval_worker as worker
    from tools.approval_context import get_current_session_key, set_current_session_key
    from tools.file_approval_payload import prepare_payload

    home, workspace = tmp_path / "home", tmp_path / "ws"
    home.mkdir()
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("old\n")
    db = kb.init_db(db_path=tmp_path / "diag.db")
    conn = connect(db)
    previous_session = get_current_session_key()
    try:
        tid = kb.create_task(conn, title="diag fixture", assignee="fixture",
                             workspace_kind="dir", workspace_path=str(workspace))
        kb.recompute_ready(conn)
        task = kb.claim_task(conn, tid)
        _set_worker_pid(conn, tid, os.getpid())
        for key, value in {"HERMES_HOME": str(home), "HERMES_KANBAN_DB": str(db),
                           "HERMES_KANBAN_TASK": tid, "HERMES_KANBAN_RUN_ID": str(task.current_run_id),
                           "HERMES_KANBAN_CLAIM_LOCK": task.claim_lock, "TERMINAL_ENV": "local",
                           "TERMINAL_CWD": str(workspace)}.items():
            monkeypatch.setenv(key, value)
        monkeypatch.delenv("HERMES_DELEGATED_CHILD_CONTEXT", raising=False)
        set_current_session_key("diag-session")
        payload = prepare_payload("write_file", [str(workspace / "AGENTS.md")],
                                  ["AGENTS.md"], "diag", content="approved\n")
        request = worker._create_and_pause(conn, payload)

        view = diag.project(conn, journal.get_request(conn, request.request_id))
        assert view["phase"] == diag.AWAITING_HUMAN
        assert view["reason"] == diag.HUMAN_DECISION_PENDING

        assert record_human_decision(conn, request.request_id,
                                     expected_hash=request.request_hash,
                                     decision=journal.GRANTED, decided_by="fixture-human",
                                     decision_surface="desktop")
        view = diag.project(conn, journal.get_request(conn, request.request_id))
        assert view["phase"] == diag.AWAITING_ADMISSION
        assert view["reason"] == diag.RESUME_REASON_NOT_YET_OBSERVED

        # Controle negativo: com observação de capacidade, o motivo muda — e a
        # ação sugerida nomeia o teto que o operador precisa liberar.
        diag.record_progress(conn, task_id=tid, run_id=task.current_run_id,
                             request_id=request.request_id, phase=diag.AWAITING_ADMISSION,
                             reason_code=diag.HOST_CAPACITY)
        view = diag.project(conn, journal.get_request(conn, request.request_id))
        assert view["reason"] == diag.HOST_CAPACITY
        assert "max_in_progress" in view["next_action"]
    finally:
        set_current_session_key(previous_session)
        conn.close()


def test_notice_budget_is_durable_per_transport_generation(board):
    """Falha consome orçamento; esgotar para de tentar; reconectar reabre.

    Três contratos num só laço, porque separá-los esconderia a interação: o
    orçamento é por (request, geração), é lido do banco (outro processo vê o
    mesmo número) e uma geração nova não herda o esgotamento da anterior.
    """
    tid, task = _task(board)
    kw = dict(task_id=tid, run_id=task.current_run_id, request_id="ap_n", limit=2)

    assert diag.notice_budget_open(board, "ap_n", "gen-1", limit=2)
    assert diag.record_notice_outcome(board, generation="gen-1", delivered=False, **kw) == "failed"
    assert diag.notice_budget_open(board, "ap_n", "gen-1", limit=2)
    assert diag.record_notice_outcome(board, generation="gen-1", delivered=False, **kw) == "exhausted"
    assert not diag.notice_budget_open(board, "ap_n", "gen-1", limit=2)

    # Reconexão real = geração nova: orçamento limpo, sem tocar no histórico.
    assert diag.notice_budget_open(board, "ap_n", "gen-2", limit=2)
    assert diag.record_notice_outcome(board, generation="gen-2", delivered=True, **kw) == "delivered"

    # Esgotar NÃO mexeu no pedido: nenhum evento de decisão foi criado.
    kinds = {row[0] for row in board.execute("SELECT DISTINCT kind FROM task_events")}
    assert not (kinds & {"approval_granted", "approval_denied", "approval_cancelled"})


def test_a_human_retry_reopens_the_notice_budget_without_deciding(board):
    """'Retry notice' zera a contagem do orçamento e não decide nada."""
    tid, task = _task(board)
    kw = dict(task_id=tid, run_id=task.current_run_id, request_id="ap_r", limit=1)
    assert diag.record_notice_outcome(board, generation="gen-1", delivered=False, **kw) == "exhausted"
    assert not diag.notice_budget_open(board, "ap_r", "gen-1", limit=1)

    diag.request_notice_retry(board, task_id=tid, run_id=task.current_run_id, request_id="ap_r")
    assert diag.notice_budget_open(board, "ap_r", "gen-1", limit=1)
    # Controle negativo: o retry de OUTRA request não reabre esta.
    assert diag.record_notice_outcome(board, generation="gen-1", delivered=False, **kw) == "exhausted"
    diag.request_notice_retry(board, task_id=tid, run_id=task.current_run_id, request_id="ap_other")
    assert not diag.notice_budget_open(board, "ap_r", "gen-1", limit=1)


def test_transport_generation_is_stable_per_object_and_new_per_reconnect():
    """A geração segue o OBJETO de transporte, não o relógio nem ``id()``."""
    class FakeTransport:
        pass

    first = FakeTransport()
    assert diag.transport_generation(first) == diag.transport_generation(first)
    assert diag.transport_generation(FakeTransport()) != diag.transport_generation(first)
    # Transporte que recusa atributo não quebra a entrega; só perde granularidade.
    assert diag.transport_generation(object()).endswith(":unstamped")
    assert diag.transport_generation(None) == "none"


def test_a_broken_attempt_limit_never_becomes_unlimited(monkeypatch):
    """Config inválida cai no default, nunca em 'tentar para sempre'."""
    for bad in ("", "abc", 0, -5, None, [3]):
        monkeypatch.setattr("hermes_cli.config.load_config_readonly",
                            lambda bad=bad: {"kanban": {"approval_notice_max_attempts": bad}})
        assert diag.resolve_notice_max_attempts() == diag.DEFAULT_NOTICE_MAX_ATTEMPTS
    monkeypatch.setattr("hermes_cli.config.load_config_readonly",
                        lambda: {"kanban": {"approval_notice_max_attempts": 7}})
    assert diag.resolve_notice_max_attempts() == 7
