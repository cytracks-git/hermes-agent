"""Classificação da morte do worker: cota mascarada de crash, e a causa dos "cegos".

Card t_38817b72. Medido no board atlas (7 dias, 894 runs): 219 runs (24,5%)
morreram sem entregar. Destes, 30 traziam ``429`` na própria saída do worker mas
foram gravados como ``crashed`` — que conta falha e gasta o breaker — em vez de
``rate_limited``, que faz requeue sem contar. Outros 35 morreram com
``pid N not alive`` e uma saída composta só de ruído do runtime
(``MallocStackLogging``), sem causa auditável.

A raiz é ``_classify_dead_worker_exit``: ela só olha o código de saída. Um worker
morto por cota que NÃO conseguiu escrever seu trailer de saída (morto pelo
provider, pelo host, ou sem chegar ao epílogo) cai em ``unknown`` -> ``crashed``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    """HERMES_HOME isolado com um kanban.db vazio."""
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def _write_worker_log(task_id: str, text: str) -> None:
    path = kb.worker_log_path(task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# Ruído real colhido dos runs cegos do board atlas: o runtime do macOS imprime
# isto por processo filho, e ele é a ÚLTIMA coisa no log — então uma janela de
# cauda ingênua devolve só isto e perde a causa.
_MALLOC_NOISE = "\n".join(
    f"python({4500 + i}) MallocStackLogging: can't turn off malloc stack "
    "logging because it was not enabled." for i in range(40)
)

_QUOTA_OUTPUT = (
    "429: This request would exceed your account's rate limit. "
    "Please try again later. Anthropic rate-limited every one of 3 attempts."
)


def _dead_worker_with_log(task_id: str, log_text: str, pid: int = 999001):
    """Classifica um pid NUNCA reapado (kind ``unknown``) cujo log diz o porquê."""
    _write_worker_log(task_id, log_text)
    return kbd._classify_dead_worker(pid, "host:w0", task_id=task_id)


# ---------------------------------------------------------------------------
# Item 1 — 429 não pode ser gravado como crash
# ---------------------------------------------------------------------------


def test_quota_wall_sem_trailer_nao_e_crash(kanban_home):
    """NEGATIVO da classe: a saída do worker diz 429, o código de saída não diz nada.

    Este é o caso dos 30 runs medidos. Tem de virar ``rate_limited`` (requeue sem
    contar falha), não ``crashed``.
    """
    dead = _dead_worker_with_log("t_quota", _QUOTA_OUTPUT)

    assert dead.rate_limited is True, (
        "429 na saída do worker foi classificado como falha do card: "
        f"outcome={dead.run_outcome!r} error={dead.error_text!r}"
    )
    assert dead.run_outcome == "rate_limited"
    assert dead.event_kind == "rate_limited"


def test_quota_wall_nao_gasta_o_breaker(kanban_home, monkeypatch):
    """Ponta a ponta: seis mortes por cota sem trailer não podem bloquear o card.

    ``DEFAULT_FAILURE_LIMIT`` é 2; se qualquer uma contasse, o card estaria
    ``blocked`` — que é a perda de capacidade que o card mede.
    """
    monkeypatch.setattr(kb, "_pid_alive", lambda _pid: False)
    monkeypatch.setenv("HERMES_KANBAN_CRASH_GRACE_SECONDS", "0")

    with kbc.connect() as conn:
        host = kb._claimer_id().split(":", 1)[0]
        tid = kb.create_task(conn, title="cota", assignee="a")
        _write_worker_log(tid, _QUOTA_OUTPUT)

        for i in range(6):
            pid = 980000 + i
            kb.claim_task(conn, tid, claimer=f"{host}:w{i}")
            conn.execute(
                "UPDATE tasks SET worker_pid=? WHERE id=?", (pid, tid))
            conn.commit()

            crashed = kbd.detect_crashed_workers(conn)
            assert tid not in crashed, f"hit {i}: cota contabilizada como crash"

            task = kb.get_task(conn, tid)
            assert task.status == "ready", f"hit {i}: status={task.status}"
            assert task.consecutive_failures == 0, (
                f"hit {i}: cota gastou retry (consecutive_failures="
                f"{task.consecutive_failures})")

        outcomes = [r["outcome"] for r in conn.execute(
            "SELECT outcome FROM task_runs WHERE task_id=? AND outcome IS NOT NULL",
            (tid,)).fetchall()]
        assert "rate_limited" in outcomes
        assert "crashed" not in outcomes, f"gravou crash por cota: {outcomes}"


# --- CONTROLE POSITIVO: o sensor não pode chamar tudo de cota ---


@pytest.mark.parametrize("saida", [
    "Traceback (most recent call last): ZeroDivisionError: division by zero",
    "fatal: repository not found",
    # A armadilha: o worker RODOU um comando cujo nome contém o número, mas
    # não foi throttled. Casar '429' solto transformaria isto em falso-verde.
    "$ grep -c 429 access.log\n429 matches in the log file",
])
def test_crash_de_verdade_continua_crash(kanban_home, saida):
    """POSITIVO: falha real do card continua ``crashed`` e continua gastando retry.

    Um classificador que devolvesse ``rate_limited`` para tudo esconderia falha
    real como "cota" e o card nunca bloquearia — falso-verde pior que o defeito.
    """
    dead = _dead_worker_with_log("t_crash", saida)

    assert dead.rate_limited is False, (
        f"falha real classificada como cota: {saida!r}")
    assert dead.run_outcome == "crashed"


# ---------------------------------------------------------------------------
# Item 2 — os 35 cegos precisam de causa
# ---------------------------------------------------------------------------


def test_causa_real_sobrevive_ao_ruido_do_runtime(kanban_home):
    """A causa fica ANTES de 40 linhas de ruído do runtime; ela tem de chegar ao board.

    Replica o run cego medido: a mensagem real do provider é empurrada para fora
    da janela de cauda pelo ``MallocStackLogging``, e o board recebe só o ruído.
    """
    causa = "Error: model 'claude-opus-4' was retired on 2026-01-01 (404)"
    dead = _dead_worker_with_log("t_cego", f"{causa}\n{_MALLOC_NOISE}\n")

    assert "retired" in dead.error_text, (
        "a causa real não chegou ao board; error_text ficou: "
        f"{dead.error_text!r}")
    assert "MallocStackLogging" not in dead.error_text, (
        "ruído do runtime ocupou o diagnóstico")


def test_sem_causa_alguma_diz_que_nao_mediu(kanban_home):
    """Log só com ruído: o board tem de dizer que não há causa, não fingir uma."""
    dead = _dead_worker_with_log("t_so_ruido", _MALLOC_NOISE)

    assert "MallocStackLogging" not in dead.error_text
    assert "not alive" in dead.error_text
