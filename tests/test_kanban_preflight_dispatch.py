"""Prova fim-a-fim: o preflight barra o spawn no DISPATCHER REAL.

A bateria unitaria prova que o veredito e correto. Ela NAO prova que o
dispatcher o obedece -- um preflight correto e desligado do caminho real e
codigo orfao, e foi assim que a regra dos wrappers falhou antes (texto que
ninguem aplica).

Aqui roda ``dispatch_once`` de verdade, sobre um kanban.db de verdade, com um
``spawn_fn`` que REGISTRA cada chamada. A pergunta de cada caso e sempre a
mesma: o worker foi criado, sim ou nao?

MUTANTE DO MECANISMO: o primeiro caso desliga o preflight (monkeypatch) e
mostra que o MESMO card SPAWNA. Sem essa linha, "nao spawnou" nao provaria
nada -- poderia ser qualquer outra guarda do dispatcher barrando o card.
"""
from __future__ import annotations

import json
import time

import pytest
import yaml

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kb_connect
from hermes_cli import kanban_db_dispatch as kdd
from tests.test_kanban_preflight import (
    api_key_ok, make_profile, oauth_429, oauth_ok, resolver_for,
)


@pytest.fixture()
def board(tmp_path, monkeypatch):
    """kanban.db real e isolado. ``connect`` ja cria o schema na primeira vez."""
    monkeypatch.setenv("HERMES_KANBAN_DB", str(tmp_path / "kanban.db"))
    return kb_connect.connect(tmp_path / "kanban.db")


class Spawns(list):
    """spawn_fn que so anota; nunca cria processo.

    Funcao-fabrica, e nao classe-com-``__call__``: ``_call_spawn_fn`` inspeciona
    a assinatura do callable, e a de uma instancia nao expoe os parametros.
    """


def spawns_fn(registro: list):
    def spawn_fn(task, workspace, board=None):
        registro.append(task.id)
        return 4242
    return spawn_fn


def rota(monkeypatch, homes):
    """Faz o preflight resolver perfis para as fixtures, e nao para ~/.hermes."""
    from hermes_cli import kanban_preflight as pf

    monkeypatch.setattr(pf, "profile_home", resolver_for(homes))
    # O dispatcher pergunta ao modulo de perfis se o assignee existe; sem isto
    # todo card cairia em skipped_nonspawnable e o teste mediria a guarda errada.
    monkeypatch.setattr(kdd, "_profile_exists_fn", lambda: (lambda n: n in homes))


def novo_card(conn, assignee, **kw):
    """Devolve o ID do card. Sem pais, ``create_task`` ja nasce ``ready``."""
    return kb.create_task(conn, title="t", body="b", assignee=assignee, **kw)


def tick(conn, spawns, **kw):
    return kdd.dispatch_once(conn, spawn_fn=spawns_fn(spawns), **kw)


# --------------------------------------------------------------------------
# MUTANTE DO MECANISMO: sem o preflight, o mesmo card spawna
# --------------------------------------------------------------------------

def test_mutante_sem_preflight_o_card_ruim_spawna(board, tmp_path, monkeypatch):
    """Linha de base. Se este caso nao spawnasse, todos os outros seriam vacuos."""
    home = make_profile(tmp_path, "executor", pool={"openai-codex": [oauth_429()]},
                        model="gpt-6-astra", provider="openai-codex", fallbacks=[])
    rota(monkeypatch, {"executor": home})
    # Desliga SO o preflight, deixando o resto do dispatcher intacto.
    monkeypatch.setattr(kdd, "_preflight_verdict", lambda *a, **k: None)
    task_id = novo_card(board, "executor")
    spawns = Spawns()
    tick(board, spawns)
    assert spawns == [task_id], "sem preflight o dispatcher spawna este card"


# --------------------------------------------------------------------------
# NEGATIVO: com o preflight ligado, o mesmo card NAO spawna
# --------------------------------------------------------------------------

def test_negativo_credencial_429_sem_fallback_nao_spawna(board, tmp_path, monkeypatch):
    """CASO B, no motor real: o gasto que run290 fez nao acontece mais."""
    home = make_profile(tmp_path, "executor", pool={"openai-codex": [oauth_429()]},
                        model="gpt-6-astra", provider="openai-codex", fallbacks=[])
    rota(monkeypatch, {"executor": home})
    task_id = novo_card(board, "executor")
    spawns = Spawns()
    result = tick(board, spawns)

    assert spawns == [], "o preflight deixou o worker nascer"
    assert [t for t, _ in result.preflight_refused] == [task_id]
    reason = dict(result.preflight_refused)[task_id]
    # A janela vem da fixture (6d), mas o texto mostra o que FALTA e trunca
    # para baixo ("5d left"): afirmar "6d" seria fixar o numero da fixture, nao
    # a informacao que o operador precisa. Exijo a janela + a proxima acao.
    assert "left)" in reason and "route this task" in reason
    assert "auth add" not in reason, "ha credencial; o problema e quota, nao ausencia"


def test_negativo_perfil_inexistente_nao_spawna(board, tmp_path, monkeypatch):
    """Caso t_aee9533c: assignee 'reviewer' quando o perfil e 'revisor'."""
    home = make_profile(tmp_path, "revisor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    # 'reviewer' EXISTE para o dispatcher mas nao para o preflight: e assim que
    # se isola o preflight da guarda de profile_exists que ja existia.
    from hermes_cli import kanban_preflight as pf
    monkeypatch.setattr(pf, "profile_home", resolver_for({"revisor": home}))
    monkeypatch.setattr(kdd, "_profile_exists_fn", lambda: (lambda n: True))
    task_id = novo_card(board, "reviewer")
    spawns = Spawns()
    result = tick(board, spawns)

    assert spawns == []
    assert [t for t, _ in result.preflight_refused] == [task_id]


def test_negativo_rota_paga_nao_spawna(board, tmp_path, monkeypatch):
    home = make_profile(
        tmp_path, "executor",
        pool={"openai-codex": [oauth_429()], "openrouter": [api_key_ok()]},
        model="gpt-6-astra", provider="openai-codex",
        fallbacks=[{"provider": "openrouter", "model": "m", "enabled": True}])
    rota(monkeypatch, {"executor": home})
    task_id = novo_card(board, "executor")
    spawns = Spawns()
    result = tick(board, spawns)

    assert spawns == []
    assert "API key" in dict(result.preflight_refused)[task_id]


# --------------------------------------------------------------------------
# POSITIVO: o preflight nao pode virar um freio geral
# --------------------------------------------------------------------------

def test_positivo_card_saudavel_spawna_normalmente(board, tmp_path, monkeypatch):
    home = make_profile(tmp_path, "executor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    rota(monkeypatch, {"executor": home})
    task_id = novo_card(board, "executor")
    spawns = Spawns()
    result = tick(board, spawns)

    assert spawns == [task_id]
    assert result.preflight_refused == []


def test_positivo_fallback_vivo_spawna_e_o_card_nao_para(board, tmp_path, monkeypatch):
    home = make_profile(
        tmp_path, "executor",
        pool={"openai-codex": [oauth_429()], "anthropic": [oauth_ok("an9")]},
        model="gpt-6-astra", provider="openai-codex",
        fallbacks=[{"provider": "anthropic", "model": "claude-opus-5", "enabled": True}])
    rota(monkeypatch, {"executor": home})
    task_id = novo_card(board, "executor")
    spawns = Spawns()
    result = tick(board, spawns)

    assert spawns == [task_id]
    assert result.preflight_refused == []


def test_positivo_um_card_ruim_nao_bloqueia_o_card_bom(board, tmp_path, monkeypatch):
    """A recusa e POR CARD. Um card sem rota nao pode parar a fila inteira."""
    bom = make_profile(tmp_path, "executor", pool={"anthropic": [oauth_ok()]},
                       model="claude-opus-5", provider="anthropic")
    ruim = make_profile(tmp_path, "pesquisa", pool={}, model="m", provider="openai-codex")
    rota(monkeypatch, {"executor": bom, "pesquisa": ruim})
    t_ruim_id = novo_card(board, "pesquisa")
    t_bom_id = novo_card(board, "executor")
    spawns = Spawns()
    result = tick(board, spawns)

    assert t_bom_id in spawns
    assert t_ruim_id not in spawns
    assert [t for t, _ in result.preflight_refused] == [t_ruim_id]


# --------------------------------------------------------------------------
# O card nunca para em silencio
# --------------------------------------------------------------------------

def test_recusa_grava_evento_legivel_com_proxima_acao(board, tmp_path, monkeypatch):
    home = make_profile(tmp_path, "pesquisa", pool={}, model="m", provider="openai-codex")
    rota(monkeypatch, {"pesquisa": home})
    task_id = novo_card(board, "pesquisa")
    tick(board, Spawns())

    rows = board.execute(
        "SELECT payload FROM task_events WHERE task_id=? AND kind='preflight_refused'",
        (task_id,)).fetchall()
    assert rows, "recusa sem evento e exatamente o silencio que o card proibe"
    payload = json.loads(rows[-1]["payload"])
    assert "auth_missing" in payload["codes"]
    assert "auth add" in payload["reason"]


def test_evento_de_recusa_nao_carrega_token(board, tmp_path, monkeypatch):
    home = make_profile(
        tmp_path, "executor",
        pool={"openai-codex": [oauth_429()], "openrouter": [api_key_ok()]},
        model="gpt-6-astra", provider="openai-codex",
        fallbacks=[{"provider": "openrouter", "model": "m"}])
    rota(monkeypatch, {"executor": home})
    task_id = novo_card(board, "executor")
    tick(board, Spawns())

    rows = board.execute(
        "SELECT payload FROM task_events WHERE task_id=? AND kind='preflight_refused'",
        (task_id,)).fetchall()
    blob = "".join(r["payload"] for r in rows)
    assert "SEGREDO-NAO-PODE-VAZAR" not in blob and "sk-SEGREDO-PAGO" not in blob


def test_dry_run_nao_grava_evento(board, tmp_path, monkeypatch):
    home = make_profile(tmp_path, "pesquisa", pool={}, model="m", provider="openai-codex")
    rota(monkeypatch, {"pesquisa": home})
    task_id = novo_card(board, "pesquisa")
    result = tick(board, Spawns(), dry_run=True)

    assert [t for t, _ in result.preflight_refused] == [task_id]
    rows = board.execute(
        "SELECT 1 FROM task_events WHERE task_id=? AND kind='preflight_refused'",
        (task_id,)).fetchall()
    assert rows == []


# --------------------------------------------------------------------------
# FAIL-OPEN: preflight quebrado nao pode parar o board
# --------------------------------------------------------------------------

def test_preflight_que_explode_nao_segura_o_card(board, tmp_path, monkeypatch):
    """Guarda que para tudo quando ELA quebra e pior que o defeito que evita."""
    home = make_profile(tmp_path, "executor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    rota(monkeypatch, {"executor": home})

    from hermes_cli import kanban_preflight as pf

    def explode(**kw):
        raise RuntimeError("preflight quebrado de proposito")

    monkeypatch.setattr(pf, "preflight", explode)
    task_id = novo_card(board, "executor")
    spawns = Spawns()
    result = tick(board, spawns)

    assert spawns == [task_id], "fail-open: o card tem de spawnar mesmo assim"
    assert result.preflight_refused == []


def test_o_card_nao_e_reprovado_por_falta_de_medicao(board, tmp_path, monkeypatch):
    """auth.json ilegivel e NAO MEDIDO -- e nao-medido recusa, mas DECLARANDO.

    Este e o par honesto do fail-open acima: quando o preflight RODA e nao
    consegue medir, ele recusa com codigo proprio em vez de fingir verde.
    """
    home = tmp_path / "ilegivel"
    home.mkdir()
    (home / "auth.json").write_text("{ nao e json", encoding="utf-8")
    (home / "config.yaml").write_text(
        yaml.safe_dump({"model": {"default": "m", "provider": "p"}}), encoding="utf-8")
    rota(monkeypatch, {"executor": home})
    task_id = novo_card(board, "executor")
    tick(board, Spawns())

    rows = board.execute(
        "SELECT payload FROM task_events WHERE task_id=? AND kind='preflight_refused'",
        (task_id,)).fetchall()
    assert "auth_not_measured" in json.loads(rows[-1]["payload"])["codes"]


# --------------------------------------------------------------------------
# Custo: o preflight roda por tick sem chamar modelo
# --------------------------------------------------------------------------

def test_tick_inteiro_nao_abre_socket(board, tmp_path, monkeypatch):
    import socket

    home = make_profile(tmp_path, "executor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    rota(monkeypatch, {"executor": home})
    novo_card(board, "executor")

    def proibido(*a, **k):
        raise AssertionError("o tick abriu socket")

    monkeypatch.setattr(socket.socket, "connect", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)
    spawns = Spawns()
    tick(board, spawns)
    assert len(spawns) == 1
