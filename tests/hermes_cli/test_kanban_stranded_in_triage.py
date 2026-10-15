"""``triage`` é a lane que nenhum varredor lê — e que não tinha alarme nenhum.

Medido no board atlas em 23/09: 24 cards em ``triage``, o mais velho há 4,7
dias, sem um único diagnóstico. O estado é permanente por construção:

- ``kanban_db.recompute_ready`` só reavalia ``status IN ('todo','blocked')``,
  então nem o fechamento do pai reavalia um card de triage;
- ``kanban_db_dispatch.dispatch_once`` só enumera ``_lane_rows(conn,'ready')``
  e ``_lane_rows(conn,'review')``;
- ``kanban_diagnostics._RULES`` não tinha nenhuma regra que olhasse a lane.

Logo ninguém dispatcha, ninguém promove e ninguém avisa. Este arquivo é o
vermelho da base do sensor que faltava, mais os controles que provam que ele
não acusa todo mundo (positivo) e que a lane certa é a coberta (negativo).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd
from hermes_cli import kanban_diagnostics as kd


THRESHOLD = kd.DEFAULT_CONFIG["triage_stranded_threshold_seconds"]


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    db_path = kb.kanban_db_path(board="default")
    kb._INITIALIZED_PATHS.discard(str(db_path.resolve()))
    kb.init_db()
    return home


@pytest.fixture
def conn(kanban_home):
    with kbc.connect() as c:
        yield c


def _task(**overrides):
    base = {
        "id": "t_triage0",
        "title": "demo",
        "body": "corpo especificado",
        "assignee": "executor",
        "status": "triage",
        "created_at": 0,
        "consecutive_failures": 0,
        "last_failure_error": None,
    }
    base.update(overrides)
    return base


def _event(kind, ts):
    return {"kind": kind, "created_at": int(ts), "payload": None}


def _kinds(task, events, now):
    return [d.kind for d in kd.compute_task_diagnostics(task, events, [], now=now)]


def _only(task, events, now):
    hits = [d for d in kd.compute_task_diagnostics(task, events, [], now=now)
            if d.kind == "stranded_in_triage"]
    assert len(hits) == 1, f"esperado exatamente 1 diagnóstico, veio {len(hits)}"
    return hits[0]


class TestFiresOnTheMeasuredClass:
    def test_the_measured_card_fires(self):
        """O caso medido: card em triage há 4,7 dias. Vermelho na base."""
        now = 1_000_000
        age = int(4.7 * 86400)
        d = _only(_task(), [_event("created", now - age)], now)

        assert d.kind == "stranded_in_triage"
        assert d.severity == "critical", "4,7d é >6x o limiar de 4h"
        assert d.data["age_seconds"] == age
        assert d.data["triage_since"] == now - age

    def test_detail_diz_a_verdade_medida_sobre_o_dispatcher(self):
        """O texto não pode prometer que um tick resolve — nenhum tick lê a lane."""
        now = 1_000_000
        d = _only(_task(), [_event("created", now - 2 * THRESHOLD)], now)

        assert "hermes kanban promote t_triage0" in d.detail
        assert "hermes kanban specify t_triage0" in d.detail
        assert "'ready' and 'review'" in d.detail

    @pytest.mark.parametrize("age_mult, expected", [
        (1.0, "warning"), (1.9, "warning"),
        (2.0, "error"), (5.9, "error"),
        (6.0, "critical"), (20.0, "critical"),
    ])
    def test_severity_escala_com_a_idade(self, age_mult, expected):
        now = 10_000_000
        events = [_event("created", now - int(THRESHOLD * age_mult))]
        assert _only(_task(), events, now).severity == expected

    def test_usa_a_entrada_mais_recente_em_triage_nao_o_created_at(self):
        """Card antigo que voltou a triage AGORA (breaker) não é carimbado velho.

        ``block_loop_detected`` é a escalação de ``kanban_db._route_block``;
        contar desde o ``created`` original inflaria a idade e o alarme.
        """
        now = 10_000_000
        events = [
            _event("created", now - 30 * 86400),
            _event("block_loop_detected", now - 60),
        ]
        assert "stranded_in_triage" not in _kinds(_task(), events, now)

    def test_sem_evento_de_entrada_cai_no_created_at(self):
        """Histórico podado: created_at é o limite inferior disponível."""
        now = 10_000_000
        d = _only(_task(created_at=now - 3 * THRESHOLD), [], now)
        assert d.data["triage_since"] == now - 3 * THRESHOLD

    def test_sem_evento_e_sem_created_at_fica_calado(self):
        """Sem base temporal nenhuma, inventar idade seria pior que calar."""
        assert "stranded_in_triage" not in _kinds(_task(created_at=0), [], 10_000_000)


class TestControlePositivoNaoAcusaTodoMundo:
    """Sensor que acusa sempre é tão inútil quanto o mudo."""

    def test_triage_recente_fica_calado(self):
        now = 10_000_000
        events = [_event("created", now - int(THRESHOLD * 0.99))]
        assert "stranded_in_triage" not in _kinds(_task(), events, now)

    @pytest.mark.parametrize("status", [
        "todo", "scheduled", "ready", "running", "review",
        "blocked", "waiting_approval", "done", "archived",
    ])
    def test_nenhuma_outra_lane_e_acusada(self, status):
        """CONTROLE NEGATIVO de escopo: a classe é da lane ``triage``.

        As outras lanes têm dono: ``ready`` é de ``stranded_in_ready``,
        ``blocked`` de ``stuck_in_blocked``, ``running`` do dispatcher.
        """
        now = 10_000_000
        events = [_event("created", now - 30 * 86400)]
        assert "stranded_in_triage" not in _kinds(_task(status=status), events, now)

    def test_limiar_configuravel_e_respeitado(self):
        now = 10_000_000
        events = [_event("created", now - 3600)]
        cfg = {"triage_stranded_threshold_seconds": 600}
        hits = [d for d in kd.compute_task_diagnostics(_task(), events, [], now=now, config=cfg)
                if d.kind == "stranded_in_triage"]
        assert len(hits) == 1
        assert hits[0].data["threshold_seconds"] == 600
        # E o mesmo card com limiar maior que a idade continua calado.
        assert not [d for d in kd.compute_task_diagnostics(
            _task(), events, [], now=now, config={"triage_stranded_threshold_seconds": 7200},
        ) if d.kind == "stranded_in_triage"]


class TestActionsApontamComandoQueExiste:
    def _commands(self, d):
        return [a.payload["command"] for a in d.actions]

    def _suggested(self, d):
        return [a.payload["command"] for a in d.actions if a.suggested]

    def test_card_especificado_sugere_promote(self):
        now = 10_000_000
        d = _only(_task(), [_event("created", now - 2 * THRESHOLD)], now)

        assert self._commands(d) == [
            "hermes kanban promote t_triage0", "hermes kanban specify t_triage0",
        ]
        assert self._suggested(d) == ["hermes kanban promote t_triage0"]
        assert d.data["specified"] is True

    @pytest.mark.parametrize("missing", [{"body": ""}, {"assignee": None},
                                         {"body": "   ", "assignee": ""}])
    def test_triage_vazio_sugere_specify_nao_promote(self, missing):
        """``kanban_db.promote_task`` RECUSA triage sem corpo/assignee.

        Sugerir ``promote`` nesse estado seria mandar o operador num comando
        que falha — o sensor tem de apontar o caminho que funciona.
        """
        now = 10_000_000
        d = _only(_task(**missing), [_event("created", now - 2 * THRESHOLD)], now)

        assert self._suggested(d) == ["hermes kanban specify t_triage0"]
        assert d.data["specified"] is False

    def test_os_comandos_sugeridos_existem_no_cli(self):
        """Hint de CLI que não existe é mentira com cara de ajuda."""
        import argparse

        from hermes_cli import kanban_parser

        root = argparse.ArgumentParser(prog="hermes")
        kanban_parser.build_parser(root.add_subparsers(dest="command"))
        for verb in ("promote", "specify"):
            args = root.parse_args(["kanban", verb, "t_triage0"])
            assert getattr(args, "task_id", None) == "t_triage0", verb


class TestNoBancoReal:
    """Atravessa o kanban_db de verdade: sqlite3.Row, não dict de fixture."""

    def _diags(self, conn, tid, now):
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        events = list(conn.execute(
            "SELECT * FROM task_events WHERE task_id=? ORDER BY id", (tid,)).fetchall())
        return kd.compute_task_diagnostics(task, events, [], now=now)

    def test_card_criado_em_triage_e_acusado_e_nao_e_dispatchavel(self, conn):
        tid = kb.create_task(conn, title="zumbi", assignee="executor",
                             body="corpo", triage=True)
        assert kb.get_task(conn, tid).status == "triage"
        # Prova de que o dispatcher realmente não enxerga a lane.
        assert tid not in [r["id"] for r in kbd._lane_rows(conn, "ready")]
        assert tid not in [r["id"] for r in kbd._lane_rows(conn, "review")]

        now = int(time.time()) + 2 * int(THRESHOLD)
        assert "stranded_in_triage" in [d.kind for d in self._diags(conn, tid, now)]

    def test_promover_o_card_apaga_o_alarme(self, conn):
        """CONTROLE POSITIVO fim-a-fim: resolvido o defeito, o sensor cala."""
        tid = kb.create_task(conn, title="zumbi", assignee="executor",
                             body="corpo", triage=True)
        now = int(time.time()) + 2 * int(THRESHOLD)
        assert "stranded_in_triage" in [d.kind for d in self._diags(conn, tid, now)]

        ok, reason = kb.promote_task(conn, tid, actor="executor")
        assert ok, reason

        assert "stranded_in_triage" not in [d.kind for d in self._diags(conn, tid, now)]

    def test_card_normal_nao_dispara(self, conn):
        tid = kb.create_task(conn, title="normal", assignee="executor")
        now = int(time.time()) + 10 * int(THRESHOLD)
        assert "stranded_in_triage" not in [d.kind for d in self._diags(conn, tid, now)]


def test_a_regra_esta_registrada_em_rules():
    """Sem registro em ``_RULES`` a função é código morto e o board segue mudo."""
    assert kd._rule_stranded_in_triage in kd._RULES
