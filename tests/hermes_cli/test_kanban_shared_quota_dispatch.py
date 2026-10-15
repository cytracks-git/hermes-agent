"""Cota compartilhada chega ao OPERADOR pelo tick do dispatcher (item 4, t_38817b72).

O defeito que este arquivo fecha não é "a função calcula errado" — é MIOLO SEM
CALL SITE: a rodada anterior mediu o agrupamento e não o ligou a nada, então
``hermes kanban dispatch`` seguia mudo e o warn de "dispatcher stuck" continuava
sem causa. Diagnóstico que ninguém lê não é diagnóstico.

Por isso as provas aqui são de CAMINHO, não de cálculo:

* POSITIVO   — 2 perfis numa assinatura: o tick carrega o agrupamento e o texto
               do operador nomeia provider e perfis;
* NEGATIVO   — 1 perfil por provider: campo vazio e texto vazio. Um sensor que
               acusa sempre é tão inútil quanto um que nunca acusa;
* MUTANTE    — a versão ÓRFÃ (função existe, tick não chama) é reconstruída aqui
               e submetida ao MESMO estímulo do positivo. Se ela passar, este
               arquivo não protege nada — é a devolução do revisor virando teste.

NÃO MEDIDO aqui: que a cota compartilhada seja a CAUSA dos 429 observados no
board. O que se mede é a topologia (N perfis -> 1 assinatura) e a sua chegada à
superfície do operador. Correlação com os 429 exigiria série temporal de quota
por provider, que este host não expõe.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd
from hermes_cli import kanban_route_preflight as rp


def _perfil(home: Path, nome: str, provider: str) -> None:
    d = home / "profiles" / nome
    d.mkdir(parents=True, exist_ok=True)
    d.joinpath("config.yaml").write_text(
        f"model:\n  provider: {provider}\n  default: m-1\n", encoding="utf-8")


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / ".hermes"
    (h / "profiles").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(h))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Cache é global ao módulo: sem zerar, um teste herda a medição do outro e o
    # veredito vira sorte de ordenação. A chave é (home, mtimes), então tmp_path
    # distinto já invalida — zerar aqui é cinto além do suspensório.
    rp._quota_cache["key"] = None
    rp._quota_cache["value"] = None
    kb.init_db()
    return h


def _tick(conn):
    """Um tick real, sem spawn: o card não importa, o preenchimento importa."""
    kb.create_task(conn, title="qualquer", assignee="executor")
    return kbd.dispatch_once(conn, spawn_fn=lambda *a, **k: None, dry_run=True)


def test_positivo_tick_carrega_e_nomeia_a_cota_compartilhada(home):
    """POSITIVO: 2 perfis numa assinatura -> o tick mede e o texto nomeia."""
    _perfil(home, "executor", "anthropic")
    _perfil(home, "revisor", "anthropic")

    with kbc.connect() as conn:
        res = _tick(conn)

    # 1) O TICK carregou (é isto que a rodada anterior não fazia).
    assert res.shared_quota, (
        "DispatchResult.shared_quota vazio: o tick não chamou o agrupamento — "
        "exatamente o defeito 'miolo sem call site' que este teste fecha")
    assert sorted(res.shared_quota["anthropic"]) == ["executor", "revisor"], res.shared_quota

    # 2) A superfície que o operador lê nomeia provider e perfis.
    linha = kbd.describe_suppression([res])
    assert "shared quota" in linha and "anthropic=2 profiles" in linha, linha
    assert "executor" in linha and "revisor" in linha, linha


def test_negativo_um_perfil_por_provider_nao_inventa_alarme(home):
    """NEGATIVO: sem compartilhamento, campo e texto vazios."""
    _perfil(home, "executor", "anthropic")
    _perfil(home, "revisor", "openai-codex")

    with kbc.connect() as conn:
        res = _tick(conn)

    assert res.shared_quota == {}, (
        f"sensor acusou compartilhamento onde cada perfil tem seu provider: {res.shared_quota}")
    assert "shared quota" not in kbd.describe_suppression([res])


def test_mutante_versao_orfa_morre_sob_o_mesmo_estimulo(home, monkeypatch):
    """MUTANTE: a função existe e mede certo, mas o tick NÃO a chama.

    É a rodada anterior, reconstruída. Mesmo estímulo do positivo. Se este
    corpo passar, o teste positivo está medindo a função em vez do caminho.
    """
    _perfil(home, "executor", "anthropic")
    _perfil(home, "revisor", "anthropic")

    # A função continua correta e disponível — só o call site do tick morre.
    assert sorted(rp.shared_quota_groups(use_cache=False)["anthropic"]) == \
        ["executor", "revisor"], "o mutante deve preservar a função, só cortar o call site"
    monkeypatch.setattr(kbd, "_shared_quota_groups", lambda: {})

    with kbc.connect() as conn:
        res = _tick(conn)

    assert not res.shared_quota, "monkeypatch do mutante não pegou"
    assert "shared quota" not in kbd.describe_suppression([res]), (
        "com o call site cortado o operador não vê nada — é este o defeito devolvido")


def test_cache_invalida_quando_o_operador_corrige_a_rota(home):
    """O cache não pode fossilizar a rota: editar o config remede na hora.

    Controle do cache em si — um cache que nunca invalida transforma a correção
    do operador em mentira que dura até o restart do dispatcher.
    """
    _perfil(home, "executor", "anthropic")
    _perfil(home, "revisor", "anthropic")
    assert rp.shared_quota_groups()["anthropic"], "primeira medição falhou"
    # Segunda chamada sem mudança: serve do cache, mesmo veredito.
    assert rp.shared_quota_groups()["anthropic"], "cache quente mudou o veredito"

    # Operador corrige a rota de um perfil: a assinatura de mtime muda.
    _perfil(home, "revisor", "openai-codex")
    assert rp.shared_quota_groups() == {}, (
        "cache ainda serve o estado velho depois da correção — está fossilizando a rota")


def test_diagnostico_nunca_derruba_o_tick(home, monkeypatch):
    """Agrupamento explodindo NÃO pode parar o despacho: é contexto, não execução."""
    _perfil(home, "executor", "anthropic")

    def _explode():
        raise RuntimeError("config ilegível")

    monkeypatch.setattr(rp, "shared_quota_groups", _explode)

    with kbc.connect() as conn:
        res = _tick(conn)  # não levanta

    assert res.shared_quota == {}
