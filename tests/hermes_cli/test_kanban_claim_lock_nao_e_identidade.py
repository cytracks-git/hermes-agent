"""Invariante: `claim_lock` NUNCA decide autoria; o run decide.

Origem medida, nao hipotese. No card `t_ad873a37` quatro runs de revisao (299,
300, 302, 303) morreram `crashed` porque o revisor escreveu:

    "o claim_lock do card e 142430MBP:57433 — e 57433 e o avo do meu processo.
     O run de revisao foi despachado para a mesma sessao que escreveu o codigo."

O pid 57433 e o processo do GATEWAY, avo de todo worker do board. Medido no
board real: aquele unico lock serviu 29 runs, 14 cards e os perfis executor,
pesquisa e revisor; e os runs daquele card rodaram em 17 processos DIFERENTES.
A premissa "e meu avo, logo sou eu" e verdadeira sempre e nao distingue nada.

Cada teste abaixo traz seu controle:
  - negativo: sabotar o estado (autoria e revisao no MESMO run) e exigir acusacao;
  - positivo: autoria e revisao em runs distintos e exigir liberacao.
Um sensor que so acusa, ou que nunca acusa, nao mede nada.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc


@pytest.fixture
def conn(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    db_path = kb.kanban_db_path(board="default")
    kb._INITIALIZED_PATHS.discard(str(db_path.resolve()))
    kb.init_db()
    with kbc.connect() as c:
        yield c


# O lock real que apareceu nos quatro runs queimados. Usado literalmente para
# que o teste fale do defeito que aconteceu, nao de um analogo inventado.
LOCK_DO_GATEWAY = "142430MBP:57433"


def _card_com_handoff(conn, *, autor="executor", revisor="revisor",
                      lock=LOCK_DO_GATEWAY) -> tuple[str, int, int]:
    """Reconstitui a situacao real: autor entrega, revisor assume.

    Os dois runs recebem o MESMO `claim_lock` — e exatamente assim que o board
    de verdade grava, e e o que enganou o revisor.
    """
    tid = kb.create_task(conn, title="handoff", assignee=autor)
    assert kb.claim_task(conn, tid, claimer=lock) is not None
    run_autoria = kb._current_run_id(conn, tid)
    kb.request_review(conn, tid, summary="entreguei", expected_run_id=run_autoria)

    conn.execute("UPDATE tasks SET assignee = ? WHERE id = ?", (revisor, tid))
    assert kb.claim_review_task(conn, tid, claimer=lock) is not None
    run_revisao = kb._current_run_id(conn, tid)
    assert run_autoria != run_revisao, "fixture invalida: precisa de DOIS runs"
    return tid, run_autoria, run_revisao


def test_locks_iguais_nao_fazem_autoria_igual(conn):
    """CONTROLE POSITIVO: runs distintos sob o MESMO lock -> nao e autorrevisao."""
    tid, run_autoria, run_revisao = _card_com_handoff(conn)

    lock_autoria = conn.execute(
        "SELECT claim_lock FROM task_runs WHERE id = ?", (run_autoria,)).fetchone()["claim_lock"]
    lock_revisao = conn.execute(
        "SELECT claim_lock FROM task_runs WHERE id = ?", (run_revisao,)).fetchone()["claim_lock"]
    # A premissa do bloqueio: os locks REALMENTE sao iguais. O teste nao vence
    # por essa igualdade nao existir — ela existe, e mesmo assim nao decide.
    assert lock_autoria == lock_revisao == LOCK_DO_GATEWAY

    ident = kb.authorship_identity(conn, tid, run_id=run_revisao)
    assert ident["author"]["run_id"] == run_autoria
    assert ident["self"]["run_id"] == run_revisao
    assert ident["is_self_review"] is False, (
        "locks iguais viraram autoria igual: o falso positivo que queimou os "
        "runs 299/300/302/303 esta de volta"
    )


def test_mesmo_run_escrevendo_e_revisando_e_acusado(conn):
    """CONTROLE NEGATIVO: autorrevisao DE VERDADE tem de ser acusada."""
    tid, run_autoria, _ = _card_com_handoff(conn)
    # Sabotagem: o proprio run da autoria pergunta se e o autor.
    ident = kb.authorship_identity(conn, tid, run_id=run_autoria)
    assert ident["is_self_review"] is True, (
        "sensor cego: o run que escreveu se apresentou como revisor e passou"
    )


def test_perfil_igual_em_runs_distintos_nao_e_autorrevisao(conn):
    """Nem o nome do perfil decide: `executor` revisando outro run de `executor`
    e revisao entre sessoes distintas, nao autorrevisao."""
    tid, run_autoria, run_revisao = _card_com_handoff(conn, autor="executor", revisor="executor")
    ident = kb.authorship_identity(conn, tid, run_id=run_revisao)
    assert ident["author"]["profile"] == ident["self"]["profile"] == "executor"
    assert ident["is_self_review"] is False


def test_run_desconhecido_responde_nao_medido_e_nao_falsa_igualdade(conn):
    """Ausencia de dado nunca pode virar uma afirmacao de identidade."""
    tid, _, _ = _card_com_handoff(conn)
    ident = kb.authorship_identity(conn, tid, run_id=10_000_000)  # run que nao existe
    assert ident["self"] is None
    assert ident["is_self_review"] is None, (
        "run desconhecido produziu veredito de autoria; NAO MEDIDO virou prova"
    )


def test_env_de_outro_card_nao_identifica_este_worker(conn, monkeypatch):
    """O env so identifica o run quando o card do env e ESTE card."""
    tid, _, run_revisao = _card_com_handoff(conn)
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_outro_card")
    monkeypatch.setenv("HERMES_KANBAN_RUN_ID", str(run_revisao))
    ident = kb.authorship_identity(conn, tid)
    assert ident["self"] is None and ident["is_self_review"] is None

    # CONTROLE POSITIVO do mesmo eixo: com o card certo, o env identifica.
    monkeypatch.setenv("HERMES_KANBAN_TASK", tid)
    ident_ok = kb.authorship_identity(conn, tid)
    assert ident_ok["self"]["run_id"] == run_revisao
    assert ident_ok["is_self_review"] is False


def test_card_sem_handoff_nao_inventa_autor(conn):
    """Sem entrega anterior nao existe autor; nao se fabrica um."""
    tid = kb.create_task(conn, title="virgem", assignee="executor")
    assert kb.claim_task(conn, tid, claimer=LOCK_DO_GATEWAY) is not None
    ident = kb.authorship_identity(conn, tid, run_id=kb._current_run_id(conn, tid))
    assert ident["author"] is None
    assert ident["is_self_review"] is None


def test_run_que_so_quebrou_nao_vira_autor(conn):
    """Um run `crashed` nao entregou trabalho — os quatro do t_ad873a37 nao
    entregaram — entao ele nao pode ser apontado como autoria."""
    tid, run_autoria, run_revisao = _card_com_handoff(conn)
    # Caminho real de um revisor que morre: o reclaim fecha o run e devolve o
    # card ao status de origem (`review`). No board o outcome ficou `crashed`
    # (runs 299/300/302/303) — replico esse estado exato na linha do run.
    assert kb.reclaim_task(conn, tid, reason="worker morreu") is True
    conn.execute(
        "UPDATE task_runs SET status = 'crashed', outcome = 'crashed' WHERE id = ?",
        (run_revisao,),
    )
    assert conn.execute(
        "SELECT status FROM tasks WHERE id = ?", (tid,)).fetchone()["status"] == "review"
    assert kb.claim_review_task(conn, tid, claimer=LOCK_DO_GATEWAY) is not None
    run_novo = kb._current_run_id(conn, tid)

    ident = kb.authorship_identity(conn, tid, run_id=run_novo)
    assert ident["author"]["run_id"] == run_autoria, (
        "um run que morreu sem entregar foi promovido a autor"
    )
    assert ident["is_self_review"] is False


def test_worker_context_entrega_o_eixo_de_autoria(conn):
    """O sinal tem de CHEGAR ao worker; funcao que ninguem le e codigo orfao."""
    tid, run_autoria, run_revisao = _card_com_handoff(conn)
    texto = kb.build_worker_context(conn, tid)
    assert "## Authorship" in texto
    assert f"run {run_autoria}" in texto
    assert "dispatch lock" in texto

    # CONTROLE NEGATIVO da renderizacao: card sem handoff nao ganha a secao.
    virgem = kb.create_task(conn, title="virgem", assignee="executor")
    assert "## Authorship" not in kb.build_worker_context(conn, virgem)
