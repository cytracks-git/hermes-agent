"""Claim residual em card FORA da lane ``running`` — a classe que parqueava o board.

Medido no board atlas em 23/09: 9 cards em ``ready``, nenhum spawnando. Seis
deles carregavam ``claim_lock='142430MBP:31800'`` de um pid morto havia 3 dias.
O estado é permanente por construção:

- ``_lane_rows`` só enumera ``WHERE status = '<lane>' AND claim_lock IS NULL``;
- ``release_stale_claims``, ``reconcile_orphaned_running``,
  ``detect_crashed_workers``, ``enforce_max_runtime`` e ``detect_stale_running``
  filtram ``status = 'running'``.

Logo ninguém dispatcha e ninguém limpa. E ``stranded_in_ready`` retorna cedo
justamente quando há ``claim_lock`` ("está sendo trabalhado"), então o board
ficava sem sensor nenhum para essa classe.

O sétimo card tinha outro defeito: ``last_failure_error`` com texto de quota
carimbado pela requeue de ``rate_limited`` sobreviveu a um run posterior
``blocked``, e a proteção que existe (ver ``check_respawn_guard``, passo 1) só
olha o ``latest_run`` — superada ela, o texto velho devolvia ``blocker_auth``
para sempre.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd
from hermes_cli import kanban_diagnostics as kdiag


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_CRASH_GRACE_SECONDS", "0")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    db_path = kb.kanban_db_path(board="default")
    kb._INITIALIZED_PATHS.discard(str(db_path.resolve()))
    kb.init_db()
    return home


@pytest.fixture
def conn(kanban_home):
    with kbc.connect() as c:
        yield c


def _host() -> str:
    return kb._claimer_id().split(":", 1)[0]


def _park_with_claim(conn, tid, *, status="ready", claim_lock=None,
                     claim_expires=4_000_000_000, worker_pid=None,
                     worker_started_at=None):
    """Reproduz o zumbi medido: card fora de ``running`` com claim preenchida."""
    conn.execute(
        "UPDATE tasks SET status=?, claim_lock=?, claim_expires=?, worker_pid=?, "
        "worker_started_at=? WHERE id=?",
        (status, claim_lock if claim_lock is not None else f"{_host()}:31800",
         claim_expires, worker_pid, worker_started_at, tid),
    )
    conn.commit()


def _claim_row(conn, tid):
    return conn.execute(
        "SELECT status, claim_lock, claim_expires, worker_pid, worker_started_at "
        "FROM tasks WHERE id=?", (tid,),
    ).fetchone()


class TestReconcileParkedClaimResidue:
    def test_ready_with_dead_host_claim_is_released_and_dispatchable(
        self, conn, all_assignees_spawnable,
    ):
        """O caso medido: ``ready`` + claim de pid morto. Vermelho na base.

        Antes da correção o card não aparecia em ``_lane_rows`` (claim não-nula)
        e nenhuma varredura de reclaim o alcançava (todas filtram ``running``).
        """
        tid = kb.create_task(conn, title="zumbi", assignee="w")
        _park_with_claim(conn, tid)

        # Prova de que o card estava invisível para o dispatch.
        assert [r["id"] for r in kbd._lane_rows(conn, "ready")] == []

        released = kbd.reconcile_parked_claim_residue(conn)

        assert released == [tid]
        row = _claim_row(conn, tid)
        assert row["status"] == "ready", "a lane não é decidida por esta varredura"
        assert row["claim_lock"] is None
        assert row["claim_expires"] is None
        assert row["worker_pid"] is None
        assert row["worker_started_at"] is None
        # E agora o dispatcher enxerga o card.
        assert [r["id"] for r in kbd._lane_rows(conn, "ready")] == [tid]

    def test_live_host_local_worker_is_never_touched(self, conn):
        """CONTROLE NEGATIVO: worker VIVO desta máquina mantém a claim.

        Soltar a claim ao lado de um processo vivo abriria espaço para um
        segundo worker no mesmo card — exatamente a duplicação que as outras
        varreduras de reclaim tomam o cuidado de evitar.
        """
        tid = kb.create_task(conn, title="vivo", assignee="w")
        sleeper = subprocess.Popen(["sleep", "30"])
        try:
            fingerprint = kbd._process_fingerprint(sleeper.pid)
            _park_with_claim(
                conn, tid, claim_lock=f"{_host()}:{sleeper.pid}",
                worker_pid=sleeper.pid, worker_started_at=fingerprint,
            )

            assert kbd.reconcile_parked_claim_residue(conn) == []

            row = _claim_row(conn, tid)
            assert row["claim_lock"] == f"{_host()}:{sleeper.pid}"
            assert row["worker_pid"] == sleeper.pid
        finally:
            sleeper.terminate()
            sleeper.wait()

    def test_dead_pid_with_claim_is_released(self, conn):
        """CONTROLE POSITIVO do sensor de vida: pid morto é resíduo."""
        tid = kb.create_task(conn, title="pid-morto", assignee="w")
        dead = subprocess.Popen(["true"])
        dead.wait()
        _park_with_claim(conn, tid, claim_lock=f"{_host()}:{dead.pid}",
                         worker_pid=dead.pid)

        assert kbd.reconcile_parked_claim_residue(conn) == [tid]
        assert _claim_row(conn, tid)["claim_lock"] is None

    def test_running_and_waiting_approval_lanes_are_left_to_their_own_passes(
        self, conn,
    ):
        """CONTROLE NEGATIVO de escopo: as lanes em voo não são desta varredura.

        ``running`` é coberto por ``release_stale_claims`` /
        ``detect_crashed_workers`` (que fazem accounting de falha e matam o
        processo); ``waiting_approval`` restaura a identidade em
        ``resume_from_pause``.
        """
        running_id = kb.create_task(conn, title="em-voo", assignee="w")
        kb.claim_task(conn, running_id)
        waiting_id = kb.create_task(conn, title="espera", assignee="w")
        _park_with_claim(conn, waiting_id, status="waiting_approval")

        assert kbd.reconcile_parked_claim_residue(conn) == []

        assert _claim_row(conn, running_id)["claim_lock"] is not None
        assert _claim_row(conn, waiting_id)["claim_lock"] is not None

    def test_clean_cards_are_not_touched(self, conn):
        """CONTROLE POSITIVO: a varredura não acusa quem está são."""
        for status in ("todo", "ready", "review", "blocked", "done", "triage"):
            tid = kb.create_task(conn, title=f"ok-{status}", assignee="w")
            conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, tid))
        conn.commit()

        assert kbd.reconcile_parked_claim_residue(conn) == []

    @pytest.mark.parametrize("status", ["ready", "review", "todo", "blocked", "triage"])
    def test_every_parked_lane_is_covered(self, conn, status):
        """A classe é da LANE, não do ``ready``: qualquer lane parada conta."""
        tid = kb.create_task(conn, title=f"zumbi-{status}", assignee="w")
        _park_with_claim(conn, tid, status=status)

        assert kbd.reconcile_parked_claim_residue(conn) == [tid]
        assert _claim_row(conn, tid)["status"] == status

    def test_foreign_host_claim_is_released(self, conn):
        """Claim de outro host não pode ser verificada aqui e não segura o card.

        Um pid de outra máquina nunca será visto vivo por este processo, então
        tratá-lo como "talvez vivo" parquearia o card para sempre — o mesmo
        defeito, com outra roupa.
        """
        tid = kb.create_task(conn, title="outro-host", assignee="w")
        _park_with_claim(conn, tid, claim_lock="outra-maquina:999",
                         worker_pid=999999)

        assert kbd.reconcile_parked_claim_residue(conn) == [tid]

    def test_reconciled_event_records_the_evidence(self, conn):
        tid = kb.create_task(conn, title="zumbi", assignee="w")
        _park_with_claim(conn, tid)

        kbd.reconcile_parked_claim_residue(conn)

        recon = [e for e in kb.list_events(conn, tid) if e.kind == "reconciled"]
        assert len(recon) == 1
        assert recon[0].payload["reason"] == "parked_claim_residue"
        assert recon[0].payload["status"] == "ready"
        assert recon[0].payload["claim_lock"] == f"{_host()}:31800"

    def test_dispatch_once_releases_and_then_spawns_the_card(
        self, conn, all_assignees_spawnable,
    ):
        """Ponta a ponta pelo tick real: destravou, spawnou."""
        tid = kb.create_task(conn, title="zumbi", assignee="w")
        _park_with_claim(conn, tid)

        spawned: list[str] = []

        def _spawn(task, *a, **k):
            spawned.append(task.id)
            return True, ""

        result = kbd.dispatch_once(conn, spawn_fn=_spawn)

        assert tid in result.released_parked_claims
        assert spawned == [tid], "o card tem de voltar a ser dispatchável"

    def test_dispatch_once_respects_the_reconcile_toggle(self, conn):
        """``kanban.reconcile_orphans=false`` desliga esta varredura também."""
        tid = kb.create_task(conn, title="zumbi", assignee="w")
        _park_with_claim(conn, tid)

        result = kbd.dispatch_once(conn, spawn_fn=lambda *a, **k: (True, ""),
                                   dry_run=True, reconcile_orphans=False)

        assert result.released_parked_claims == []
        assert _claim_row(conn, tid)["claim_lock"] is not None


class TestParkedClaimDiagnostic:
    def _diags(self, conn, tid):
        task = conn.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        return kdiag.compute_task_diagnostics(task, kb.list_events(conn, tid), [])

    def test_sensor_fires_on_a_parked_claim(self, conn):
        """Hoje o board é silêncio total nesta classe — este é o sensor."""
        tid = kb.create_task(conn, title="zumbi", assignee="w")
        _park_with_claim(conn, tid)

        kinds = [d.kind for d in self._diags(conn, tid)]

        assert "parked_claim_residue" in kinds
        # Prova de que o sensor existente NÃO cobre o caso: stranded_in_ready
        # retorna cedo justamente porque há claim_lock.
        assert "stranded_in_ready" not in kinds

    def test_sensor_silent_on_a_clean_ready_card(self, conn):
        """CONTROLE POSITIVO: sensor que acusa sempre é tão inútil quanto o mudo."""
        tid = kb.create_task(conn, title="sao", assignee="w")
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
        conn.commit()

        assert "parked_claim_residue" not in [d.kind for d in self._diags(conn, tid)]

    def test_sensor_silent_on_a_healthy_running_card(self, conn):
        tid = kb.create_task(conn, title="em-voo", assignee="w")
        kb.claim_task(conn, tid)

        assert "parked_claim_residue" not in [d.kind for d in self._diags(conn, tid)]


class TestResidualFailureTextDoesNotOutliveALaterRun:
    def _seed_run(self, conn, tid, *, outcome, ended_at):
        kb.claim_task(conn, tid)
        run_id = kb.get_task(conn, tid).current_run_id
        conn.execute(
            "UPDATE task_runs SET outcome=?, status=?, ended_at=? WHERE id=?",
            (outcome, outcome, ended_at, run_id),
        )
        conn.execute(
            "UPDATE tasks SET status='ready', current_run_id=NULL, claim_lock=NULL, "
            "claim_expires=NULL, worker_pid=NULL WHERE id=?", (tid,),
        )
        conn.commit()

    def test_quota_text_superseded_by_a_later_blocked_run(self, conn, monkeypatch):
        """O caso medido (t_03aac2e3): quota em 22/09, run ``blocked`` depois.

        A proteção que já existe (passo 1 de ``check_respawn_guard``) só olha o
        ``latest_run``; superada por um run de outra natureza, o texto de quota
        antigo voltava a casar com ``_RESPAWN_BLOCKER_RE`` e devolvia
        ``blocker_auth`` para sempre. Vermelho na base.
        """
        monkeypatch.setenv("HERMES_KANBAN_RATE_LIMIT_COOLDOWN_SECONDS", "300")
        tid = kb.create_task(conn, title="quota-velha", assignee="w")
        self._seed_run(conn, tid, outcome="rate_limited", ended_at=5_000_000)
        self._seed_run(conn, tid, outcome="blocked", ended_at=5_000_500)
        conn.execute(
            "UPDATE tasks SET last_failure_error=? WHERE id=?",
            ("pid 45488 exited rate-limited (quota wall) — requeued without "
             "counting a failure", tid),
        )
        conn.commit()

        assert kbd.check_respawn_guard(conn, tid) is None

    @pytest.mark.parametrize(
        "outcome", ["completed", "review_requested", "changes_requested", "blocked"],
    )
    def test_any_later_terminal_run_supersedes_the_text(
        self, conn, monkeypatch, outcome,
    ):
        """A classe é "o worker chegou ao fim depois", não só ``blocked``."""
        monkeypatch.setenv("HERMES_KANBAN_RATE_LIMIT_COOLDOWN_SECONDS", "300")
        tid = kb.create_task(conn, title=f"depois-{outcome}", assignee="w")
        self._seed_run(conn, tid, outcome="rate_limited", ended_at=5_000_000)
        self._seed_run(conn, tid, outcome=outcome, ended_at=5_000_500)
        conn.execute(
            "UPDATE tasks SET last_failure_error=? WHERE id=?",
            ("provider quota exhausted", tid),
        )
        conn.commit()

        assert kbd.check_respawn_guard(conn, tid) is None

    def test_real_auth_failure_still_parks_the_card(self, conn, monkeypatch):
        """CONTROLE NEGATIVO: a guarda continua guardando.

        Um ``spawn_failed`` por credencial inválida NÃO é um run em que o worker
        chegou ao fim, então o texto continua sendo o diagnóstico atual e o card
        tem de ficar parado — retentar imediatamente não ajuda.
        """
        monkeypatch.setenv("HERMES_KANBAN_RATE_LIMIT_COOLDOWN_SECONDS", "0")
        tid = kb.create_task(conn, title="auth-real", assignee="w")
        self._seed_run(conn, tid, outcome="spawn_failed", ended_at=5_000_000)
        conn.execute(
            "UPDATE tasks SET last_failure_error=? WHERE id=?",
            ("provider authentication failed", tid),
        )
        conn.commit()

        assert kbd.check_respawn_guard(conn, tid) == "blocker_auth"

    def test_auth_failure_without_any_run_still_parks_the_card(
        self, conn, monkeypatch,
    ):
        """Sem run fechado não há nada que supere o texto."""
        monkeypatch.setenv("HERMES_KANBAN_RATE_LIMIT_COOLDOWN_SECONDS", "0")
        tid = kb.create_task(conn, title="sem-run", assignee="w")
        conn.execute(
            "UPDATE tasks SET last_failure_error=? WHERE id=?",
            ("401 unauthorized from provider", tid),
        )
        conn.commit()

        assert kbd.check_respawn_guard(conn, tid) == "blocker_auth"
