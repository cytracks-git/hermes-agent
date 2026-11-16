"""Re-despacho automatico de bloqueio ``transient`` (roadmap C2, card t_e0d44196).

Contrato: um ``kanban_block(kind='transient')`` volta a fila sozinho depois de
``kanban.transient_redispatch_seconds`` (lido do config.yaml real), uma vez por
bloqueio, com o motivo como handoff no contexto do proximo worker. Os outros
tipos de bloqueio continuam presos ate um humano, e o segundo transient seguido
continua indo a triage pelo disjuntor de recorrencia.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
import yaml

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd


@pytest.fixture
def kanban_home(tmp_path, monkeypatch, all_assignees_spawnable):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def _config(home: Path, seconds) -> None:
    (home / "config.yaml").write_text(
        yaml.safe_dump({"kanban": {"transient_redispatch_seconds": seconds}}), encoding="utf-8",
    )
    # load_config e cacheado por mtime/size do arquivo: escrita nova invalida.


def _block_aged(conn, assignee: str, kind: str, reason: str, age: int) -> str:
    tid = kb.create_task(conn, title=f"{kind} card", assignee=assignee)
    assert kb.claim_task(conn, tid) is not None
    assert kb.block_task(conn, tid, reason=reason, kind=kind)
    conn.execute("UPDATE task_events SET created_at = created_at - ? WHERE task_id = ?", (age, tid))
    conn.commit()
    return tid


def test_transient_block_redispatches_once_with_handoff(kanban_home):
    """Positivo + negativos: so o transient vencido volta; o handoff chega ao
    proximo worker; o segundo transient seguido cai em triage, nao em loop."""
    _config(kanban_home, 60)
    spawned: list[str] = []
    with kbc.connect() as conn:
        due = _block_aged(conn, "alice", "transient", "bun install falhou: ECONNRESET", 120)
        fresh = _block_aged(conn, "bob", "transient", "rede caiu agora", 5)
        human = _block_aged(conn, "carol", "needs_input", "qual banco usar?", 9999)
        # Card parado pelo disjuntor e classificado depois: decisao do breaker, fica.
        parked = kb.create_task(conn, title="parked", assignee="dave")
        conn.execute("UPDATE tasks SET status = 'blocked' WHERE id = ?", (parked,))
        conn.commit()
        assert kb.block_task(conn, parked, reason="classificado", kind="transient")
        conn.execute("UPDATE task_events SET created_at = created_at - 9999 WHERE task_id = ?", (parked,))
        # Transient com orcamento de falhas esgotado: o breaker manda, nao retoma.
        spent = _block_aged(conn, "erin", "transient", "flaky de novo", 9999)
        conn.execute("UPDATE tasks SET consecutive_failures = 2 WHERE id = ?", (spent,))
        conn.commit()
        res = kbd.dispatch_once(conn, spawn_fn=lambda t, ws, board=None: spawned.append(t.id))

        assert res.transient_redispatched == [due]
        assert due in spawned
        assert kb.get_task(conn, fresh).status == "blocked"
        assert kb.get_task(conn, human).status == "blocked"
        assert kb.get_task(conn, parked).status == "blocked"
        assert kb.get_task(conn, spent).status == "blocked"
        assert "bun install falhou: ECONNRESET" in kb.build_worker_context(conn, due)

        # Mesmo motivo de novo: disjuntor de recorrencia manda para triage.
        assert kb.block_task(conn, due, reason="bun install falhou de novo", kind="transient")
        assert kb.get_task(conn, due).status == "triage"
        conn.execute("UPDATE task_events SET created_at = created_at - 9999 WHERE task_id = ?", (due,))
        conn.commit()
        again = kbd.dispatch_once(conn, spawn_fn=lambda t, ws, board=None: None)
        assert due not in again.transient_redispatched
        assert kb.get_task(conn, due).status == "triage"


def test_transient_redispatch_off_keeps_block_sticky(kanban_home):
    """``0`` desliga: o transient volta a ser sticky como antes do C2."""
    _config(kanban_home, 0)
    with kbc.connect() as conn:
        tid = _block_aged(conn, "alice", "transient", "flaky", 99999)
        res = kbd.dispatch_once(conn, spawn_fn=lambda t, ws, board=None: None)
        assert res.transient_redispatched == []
        assert kb.get_task(conn, tid).status == "blocked"


def _trip_sticky(conn, tid: str) -> None:
    """Trip sticky do disjuntor (caminho crash + provider terminal: o chamador
    ja restaurou a fase, por isso ``release_claim``/``end_run`` desligados)."""
    assert kbd._record_task_failure(
        conn, tid, error="401 credencial revogada", outcome="crashed",
        force_trip=True, release_claim=False, end_run=False,
        event_payload_extra={"terminal_provider": True},
    )


def test_sticky_trip_after_manual_promote_stays_blocked(kanban_home):
    """Guardiao t_3066a937: promote manual grava ``promoted_manual`` (nao
    ``unblocked``), entao o ``blocked`` transient antigo seguia como ultimo
    evento do filtro; o trip sticky seguinte herdava ``block_kind='transient'``
    e a varredura anulava o trip. Esperado: so um humano tira o card dali."""
    _config(kanban_home, 60)
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="t", assignee="alice")
        assert kb.claim_task(conn, tid) is not None
        assert kb.block_task(conn, tid, reason="rede caiu", kind="transient")
        ok, err = kb.promote_task(conn, tid, actor="humano", reason="tenta de novo")
        assert ok, err
        _trip_sticky(conn, tid)
        assert kb.get_task(conn, tid).status == "blocked"
        conn.execute("UPDATE task_events SET created_at = created_at - 9999 WHERE task_id = ?", (tid,))
        conn.commit()
        assert kb.recompute_ready(conn) == 0
        res = kbd.dispatch_once(conn, spawn_fn=lambda t, ws, board=None: None)
        assert tid not in res.transient_redispatched
        assert kb.get_task(conn, tid).status == "blocked"
        # Humano destrava: o caminho manual continua funcionando.
        assert kb.unblock_task(conn, tid)
        assert kb.get_task(conn, tid).status == "ready"


def test_sticky_trip_before_transient_block_holds(kanban_home):
    """Trip sticky ainda sem ``unblocked`` humano, mesmo anterior ao bloqueio
    transient (promote manual no meio), segura o card: a varredura nao pode
    ser a primeira a liberar o que o disjuntor mandou para operador."""
    _config(kanban_home, 60)
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="t", assignee="alice")
        _trip_sticky(conn, tid)
        assert kb.get_task(conn, tid).status == "blocked"
        ok, err = kb.promote_task(conn, tid, actor="humano", reason="forca")
        assert ok, err
        assert kb.claim_task(conn, tid) is not None
        assert kb.block_task(conn, tid, reason="rede caiu", kind="transient")
        conn.execute("UPDATE task_events SET created_at = created_at - 9999 WHERE task_id = ?", (tid,))
        conn.commit()
        res = kbd.dispatch_once(conn, spawn_fn=lambda t, ws, board=None: None)
        assert tid not in res.transient_redispatched
        assert kb.get_task(conn, tid).status == "blocked"


def test_plain_breaker_trip_after_manual_promote_not_attributed_to_transient(kanban_home):
    """Bloqueio transient ja consumido pelo promote manual nao volta a valer:
    um trip PLANO posterior (``gave_up`` sem ``sticky``, julgado pelo contador)
    seguido de aumento de ``max_retries`` nao pode ser liberado pela varredura
    em nome de um transient que ja foi atendido."""
    _config(kanban_home, 60)
    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="t", assignee="alice")
        assert kb.claim_task(conn, tid) is not None
        assert kb.block_task(conn, tid, reason="rede caiu", kind="transient")
        ok, err = kb.promote_task(conn, tid, actor="humano", reason="tenta de novo")
        assert ok, err
        conn.execute("UPDATE tasks SET max_retries = 1 WHERE id = ?", (tid,))
        conn.commit()
        assert kbd._record_task_failure(
            conn, tid, error="boom", outcome="crashed", release_claim=False, end_run=False,
        )
        assert kb.get_task(conn, tid).status == "blocked"
        conn.execute("UPDATE tasks SET max_retries = 5 WHERE id = ?", (tid,))
        conn.execute("UPDATE task_events SET created_at = created_at - 9999 WHERE task_id = ?", (tid,))
        conn.commit()
        res = kbd.dispatch_once(conn, spawn_fn=lambda t, ws, board=None: None)
        assert tid not in res.transient_redispatched
        auto = conn.execute(
            "SELECT COUNT(*) FROM task_events WHERE task_id = ? AND kind = 'unblocked' "
            "AND json_extract(payload, '$.auto') = 'transient_redispatch'", (tid,),
        ).fetchone()[0]
        assert auto == 0


def test_informational_event_after_transient_block_still_redispatches(kanban_home):
    """Controle positivo do conserto: comentario/anexo/prioridade depois do
    bloqueio nao mudam status e nao podem matar o re-despacho."""
    _config(kanban_home, 60)
    with kbc.connect() as conn:
        tid = _block_aged(conn, "alice", "transient", "ECONNRESET", 120)
        kb.add_comment(conn, tid, "humano", "so olhando")
        kb.edit_task(conn, tid, priority=5)
        conn.execute("UPDATE task_events SET created_at = created_at - 120 WHERE task_id = ?", (tid,))
        conn.commit()
        res = kbd.dispatch_once(conn, spawn_fn=lambda t, ws, board=None: None)
        assert res.transient_redispatched == [tid]
