"""Integração do preflight de rota com o dispatcher: bloquear em vez de queimar run.

Card t_38817b72. Prova a economia real: com a rota do perfil morta, o card sai do
tick BLOQUEADO com a causa, e **nenhum run é aberto**. Antes, cada tentativa
abria e fechava um run e (classificada como crash) gastava o breaker do card.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    (home / "profiles" / "executor").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (home / "profiles" / "executor" / "config.yaml").write_text(
        "model:\n  provider: anthropic\n  default: claude-opus-5\n", encoding="utf-8")
    kb.init_db()
    return home


def _spawns_proibidos(*a, **k):
    raise AssertionError("dispatch chamou spawn com a rota morta")


def _runs(conn, tid: int | str) -> list:
    return conn.execute(
        "SELECT outcome FROM task_runs WHERE task_id=?", (tid,)).fetchall()


def test_rota_morta_bloqueia_sem_gastar_run(kanban_home, monkeypatch):
    """NEGATIVO: credencial do perfil exige relogin — bloqueia, não despacha."""
    prof = kanban_home / "profiles" / "executor"
    prof.mkdir(parents=True, exist_ok=True)
    prof.joinpath("config.yaml").write_text(
        "model:\n  provider: openai-codex\n  default: gpt-5\n", encoding="utf-8")
    # Rota comprovadamente morta: o próprio Hermes gravou que o provider
    # exige novo login (é a assinatura dos 401 medidos no board).
    (prof / "auth.json").write_text(json.dumps({"providers": {"openai-codex": {
        "tokens": {},
        "last_auth_error": {
            "code": "refresh_token_reused", "relogin_required": True,
            "message": "Codex refresh token was already consumed"}}}}),
        encoding="utf-8")

    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="rota podre", assignee="executor")

        result = kbd.dispatch_once(conn, spawn_fn=_spawns_proibidos)

        assert [e[0] for e in result.route_blocked] == [tid], (
            f"card não foi barrado pelo preflight: {result.route_blocked}")
        assert not result.spawned

        task = kb.get_task(conn, tid)
        assert task is not None
        assert task.status == "blocked", f"status={task.status}"
        assert task.block_kind == "capability", f"block_kind={task.block_kind}"
        assert task.consecutive_failures == 0, (
            "rota morta gastou o breaker do card: "
            f"{task.consecutive_failures}")
        # O que o card exige é que a rota morta não gaste uma TENTATIVA. O único
        # run existente é o que ``block_task`` sintetiza para ancorar o motivo do
        # bloqueio (``outcome='blocked'``) — registro de auditoria, não execução.
        # Nenhum run de tentativa (crashed / rate_limited / timed_out) pode existir.
        outcomes = [r[0] for r in _runs(conn, tid)]
        assert outcomes == ["blocked"], (
            f"rota morta gerou run de tentativa: {outcomes}")

        # A causa tem de ficar auditável no board, não só no log do processo.
        eventos = conn.execute(
            "SELECT payload FROM task_events WHERE task_id=? AND kind='route_preflight_blocked'",
            (tid,)).fetchall()
        assert len(eventos) == 1, f"evento de causa ausente: {eventos}"
        payload = json.loads(eventos[0][0])
        assert payload["kind"] == "revoked_credential"
        assert "openai-codex" in payload["reason"]


def test_rota_sadia_despacha_normalmente(kanban_home, monkeypatch):
    """POSITIVO: com credencial válida o preflight não pode atrapalhar o dispatch.

    Sem este caso, um preflight que barrasse tudo passaria no teste negativo e
    pararia o board inteiro.
    """
    (kanban_home / "auth.json").write_text(
        json.dumps({"providers": {"anthropic": {"api_key": "sk-abc"}}}),
        encoding="utf-8")

    spawned: list = []

    def _spawn(task, workspace, **kw):
        spawned.append(task.id)
        return 424242

    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="rota boa", assignee="executor")

        result = kbd.dispatch_once(conn, spawn_fn=_spawn)

        assert not result.route_blocked, (
            f"preflight barrou uma rota sadia: {result.route_blocked}")
        assert spawned == [tid], f"não despachou: {result}"
        assert kb.get_task(conn, tid).status == "running"
