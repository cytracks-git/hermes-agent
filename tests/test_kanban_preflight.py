"""Bateria do preflight de despacho (card t_00b18862).

Cada caso do corpo do card vira teste nomeado. Os controles negativos
importam mais que os positivos: um preflight que reprova todo mundo e tao
inutil quanto um que nunca reprova, e os dois passariam numa suite so de
caminhos felizes.

Roda sem rede e sem chamada de modelo. O perfil e sempre uma fixture em tmp,
nunca ``~/.hermes``: nenhum teste le credencial real.
"""
from __future__ import annotations

import json
import time

import pytest
import yaml

from hermes_cli import kanban_preflight as pf


# --------------------------------------------------------------------------
# Fixtures: um "perfil" e um diretorio com auth.json + config.yaml
# --------------------------------------------------------------------------

def make_profile(tmp_path, name, *, pool=None, model=None, provider=None, fallbacks=None):
    home = tmp_path / name
    home.mkdir(parents=True, exist_ok=True)
    (home / "auth.json").write_text(
        json.dumps({"credential_pool": pool or {}}), encoding="utf-8")
    cfg = {}
    if model or provider:
        cfg["model"] = {"default": model, "provider": provider}
    if fallbacks is not None:
        cfg["fallback_providers"] = fallbacks
    (home / "config.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return home


def resolver_for(mapping):
    return lambda name: mapping.get(name)


def oauth_ok(cid="aa0001"):
    return {"id": cid, "auth_type": "oauth", "source": "manual:device_code",
            "access_token": "SEGREDO-NAO-PODE-VAZAR", "last_status": "ok"}


def oauth_429(cid="bb0002", seconds_left=6 * 24 * 3600):
    return {"id": cid, "auth_type": "oauth", "source": "manual:device_code",
            "access_token": "SEGREDO-NAO-PODE-VAZAR",
            "last_status": "exhausted", "last_status_at": time.time(),
            "last_error_code": 429, "last_error_reason": "usage_limit_reached",
            "last_error_reset_at": time.time() + seconds_left}


def oauth_403(cid="cc0003"):
    return {"id": cid, "auth_type": "oauth", "source": "manual:device_code",
            "access_token": "SEGREDO-NAO-PODE-VAZAR",
            "last_status": "exhausted", "last_status_at": time.time(),
            "last_error_code": 403, "last_error_reason": "forbidden",
            "last_error_message": "billing"}


def api_key_ok(cid="dd0004"):
    return {"id": cid, "auth_type": "api_key", "source": "manual:paste",
            "access_token": "sk-SEGREDO-PAGO", "last_status": "ok"}


# --------------------------------------------------------------------------
# POSITIVO: o preflight deixa passar o que esta bom
# --------------------------------------------------------------------------

def test_positivo_perfil_com_credencial_limpa_despacha(tmp_path):
    home = make_profile(tmp_path, "executor",
                        pool={"openai-codex": [oauth_ok()]},
                        model="gpt-6-astra", provider="openai-codex")
    v = pf.preflight(task_id="t_pos", assignee="executor",
                     home_resolver=resolver_for({"executor": home}))
    assert v.ok, v.reason()
    assert v.route["effective_provider"] == "openai-codex"
    assert v.route["effective_model"] == "gpt-6-astra"


def test_positivo_nao_acusa_sempre_maioria_dos_perfis_passa(tmp_path):
    """Controle contra o sensor 'acusa sempre': 4 perfis saudaveis, 4 verdes."""
    resolved = {}
    for i, provider in enumerate(("openai-codex", "anthropic", "xai-oauth", "nous")):
        resolved[f"p{i}"] = make_profile(
            tmp_path, f"p{i}", pool={provider: [oauth_ok(f"id{i}")]},
            model="m", provider=provider)
    for name in resolved:
        v = pf.preflight(task_id="t", assignee=name, home_resolver=resolver_for(resolved))
        assert v.ok, f"{name}: {v.reason()}"


# --------------------------------------------------------------------------
# NEGATIVO: perfil / papel
# --------------------------------------------------------------------------

def test_negativo_assignee_inexistente_reprova_com_proxima_acao(tmp_path):
    """Caso real do corpo: card t_aee9533c tinha assignee 'reviewer' (existe 'revisor')."""
    home = make_profile(tmp_path, "revisor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    v = pf.preflight(task_id="t_aee9533c", assignee="reviewer",
                     home_resolver=resolver_for({"revisor": home}))
    assert not v.ok
    codes = [f.code for f in v.blocking]
    assert codes == ["profile_missing"]
    assert v.blocking[0].next_action, "bloqueio sem proxima acao e o silencio que o card proibe"


def test_negativo_assignee_vazio_reprova(tmp_path):
    v = pf.preflight(task_id="t", assignee="", home_resolver=resolver_for({}))
    assert not v.ok
    assert [f.code for f in v.blocking] == ["assignee_missing"]


def test_perfil_default_e_valido_nao_e_profiles_default(tmp_path):
    """`default` resolve para HERMES_HOME. Um preflight que procure
    profiles/default reprovaria o perfil default do sistema."""
    home = make_profile(tmp_path, "raiz", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    v = pf.preflight(task_id="t", assignee="default",
                     home_resolver=resolver_for({"default": home}))
    assert v.ok, v.reason()


def test_profile_home_usa_o_resolvedor_canonico_do_hermes():
    """Controle de nao-reimplementacao: `default` resolve, lixo nao resolve.

    Se este modulo montasse o caminho a mao (profiles/<nome>), `default` viria
    None -- e o perfil default do sistema seria reprovado por construcao.
    """
    assert pf.profile_home("default") is not None
    assert pf.profile_home("perfil-que-nao-existe-xyz") is None


# --------------------------------------------------------------------------
# NEGATIVO: auth ausente vs 429 transitorio vs 403 -- TRES decisoes distintas
# --------------------------------------------------------------------------

def test_negativo_B1_credencial_429_com_janela_e_sem_fallback_reprova(tmp_path):
    """CASO B medido: run290 morreu em 429 com a janela ja carimbada em disco."""
    home = make_profile(tmp_path, "revisor",
                        pool={"openai-codex": [oauth_429(seconds_left=6 * 24 * 3600 + 8 * 3600)]},
                        model="gpt-6-astra", provider="openai-codex", fallbacks=[])
    v = pf.preflight(task_id="t_abceecc5", assignee="revisor",
                     home_resolver=resolver_for({"revisor": home}))
    assert not v.ok
    f = v.blocking[0]
    assert f.code == "auth_unusable"
    assert "6d" in f.message, f.message  # a janela aparece na mensagem


def test_negativo_B2_fallback_habilitado_e_limpo_despacha_anunciando(tmp_path):
    """Usar fallback nao e downgrade silencioso -- desde que anuncie o efetivo."""
    home = make_profile(
        tmp_path, "executor",
        pool={"openai-codex": [oauth_429()], "anthropic": [oauth_ok("an01")]},
        model="gpt-6-astra", provider="openai-codex",
        fallbacks=[{"provider": "anthropic", "model": "claude-opus-5", "enabled": True}])
    v = pf.preflight(task_id="t", assignee="executor",
                     home_resolver=resolver_for({"executor": home}))
    assert v.ok, v.reason()
    assert v.route["effective_provider"] == "anthropic"
    assert v.route["effective_model"] == "claude-opus-5"
    assert any(f.code == "route_fallback" for f in v.findings)


def test_negativo_B3_tres_carimbos_produzem_TRES_decisoes(tmp_path):
    """`rate-limited (6d)` != `exhausted (ready to retry)` != `auth failed (403)`.

    Tratar os tres como "sem auth" e o falso-bloqueio que ja prendeu cards
    reais no board. Este teste morre se alguem colapsar os estados.
    """
    rl = make_profile(tmp_path, "a", pool={"p": [oauth_429()]}, model="m", provider="p")
    ready = make_profile(tmp_path, "b", pool={"p": [oauth_429(seconds_left=-10)]},
                         model="m", provider="p")
    failed = make_profile(tmp_path, "c", pool={"p": [oauth_403()]}, model="m", provider="p")
    res = resolver_for({"a": rl, "b": ready, "c": failed})

    v_rl = pf.preflight(task_id="t", assignee="a", home_resolver=res)
    v_ready = pf.preflight(task_id="t", assignee="b", home_resolver=res)
    v_failed = pf.preflight(task_id="t", assignee="c", home_resolver=res)

    assert not v_rl.ok
    assert v_ready.ok, "janela vencida volta a ser elegivel: " + v_ready.reason()
    assert not v_failed.ok
    # E as duas reprovas nao dizem a mesma coisa ao operador:
    assert "Waiting will not help" in v_failed.blocking[0].next_action
    assert "Waiting will not help" not in v_rl.blocking[0].next_action


def test_negativo_sem_credencial_nenhuma_reprova_diferente_de_esgotada(tmp_path):
    home = make_profile(tmp_path, "pesquisa", pool={}, model="m", provider="openai-codex")
    v = pf.preflight(task_id="t", assignee="pesquisa",
                     home_resolver=resolver_for({"pesquisa": home}))
    assert not v.ok
    assert v.blocking[0].code == "auth_missing"
    assert "auth add" in v.blocking[0].next_action


def test_auth_store_ilegivel_e_NAO_MEDIDO_nunca_verde(tmp_path):
    """existsSync/ler-falhou nao pode virar 'perfil sem credencial' e passar."""
    home = tmp_path / "quebrado"
    home.mkdir()
    (home / "auth.json").write_text("{ isto nao e json", encoding="utf-8")
    (home / "config.yaml").write_text(
        yaml.safe_dump({"model": {"default": "m", "provider": "p"}}), encoding="utf-8")
    v = pf.preflight(task_id="t", assignee="quebrado",
                     home_resolver=resolver_for({"quebrado": home}))
    assert not v.ok
    assert v.blocking[0].code == "auth_not_measured"
    assert "NOT MEASURED" in v.blocking[0].message


def test_provider_nao_resolvido_reprova(tmp_path):
    home = make_profile(tmp_path, "x", pool={"p": [oauth_ok()]})
    v = pf.preflight(task_id="t", assignee="x", home_resolver=resolver_for({"x": home}))
    assert not v.ok
    assert v.blocking[0].code == "provider_unresolved"


# --------------------------------------------------------------------------
# NEGATIVO: rota paga
# --------------------------------------------------------------------------

def test_negativo_rota_paga_por_token_como_fallback_e_recusada(tmp_path):
    home = make_profile(
        tmp_path, "executor",
        pool={"openai-codex": [oauth_429()], "openrouter": [api_key_ok()]},
        model="gpt-6-astra", provider="openai-codex",
        fallbacks=[{"provider": "openrouter", "model": "algum-modelo", "enabled": True}])
    v = pf.preflight(task_id="t", assignee="executor",
                     home_resolver=resolver_for({"executor": home}))
    assert not v.ok
    assert v.blocking[0].code == "paid_fallback_refused"


def test_controle_positivo_fallback_oauth_nao_e_confundido_com_rota_paga(tmp_path):
    """A recusa acima tem de morder SO a rota por token.

    Sem este par, 'recusar rota paga' poderia estar recusando todo fallback --
    e a bateria ficaria verde do mesmo jeito.
    """
    home = make_profile(
        tmp_path, "executor",
        pool={"openai-codex": [oauth_429()], "anthropic": [oauth_ok("an02")]},
        model="gpt-6-astra", provider="openai-codex",
        fallbacks=[{"provider": "anthropic", "model": "claude-opus-5", "enabled": True}])
    v = pf.preflight(task_id="t", assignee="executor",
                     home_resolver=resolver_for({"executor": home}))
    assert v.ok, v.reason()
    assert not any(f.code == "paid_fallback_refused" for f in v.findings)


def test_fallback_desabilitado_nao_salva_o_despacho(tmp_path):
    home = make_profile(
        tmp_path, "executor",
        pool={"openai-codex": [oauth_429()], "anthropic": [oauth_ok()]},
        model="gpt-6-astra", provider="openai-codex",
        fallbacks=[{"provider": "anthropic", "model": "claude-opus-5", "enabled": False}])
    v = pf.preflight(task_id="t", assignee="executor",
                     home_resolver=resolver_for({"executor": home}))
    assert not v.ok
    assert v.blocking[0].code == "auth_unusable"


# --------------------------------------------------------------------------
# Independencia de familia: DECLARA, nao bloqueia
# --------------------------------------------------------------------------

def test_mesma_familia_na_revisao_e_declarada_e_nao_bloqueia(tmp_path):
    """H1 aceita mesma familia para nao represar a fila; o que ele proibe e
    chamar isso de revisao cruzada. Logo: finding nao-bloqueante."""
    home = make_profile(tmp_path, "revisor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    v = pf.preflight(task_id="t", assignee="revisor", lane="review",
                     author_provider="anthropic",
                     home_resolver=resolver_for({"revisor": home}))
    assert v.ok, v.reason()
    same = [f for f in v.findings if f.code == "same_family_review"]
    assert len(same) == 1
    assert same[0].blocking is False
    assert "NOT cross-family" in same[0].message


def test_familia_diferente_na_revisao_nao_emite_declaracao(tmp_path):
    """Controle negativo do finding acima: se ele acendesse sempre, a
    declaracao viraria ruido e ninguem leria."""
    home = make_profile(tmp_path, "revisor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    v = pf.preflight(task_id="t", assignee="revisor", lane="review",
                     author_provider="openai-codex",
                     home_resolver=resolver_for({"revisor": home}))
    assert v.ok
    assert not any(f.code == "same_family_review" for f in v.findings)


def test_mesma_familia_na_lane_ready_nao_emite_declaracao(tmp_path):
    home = make_profile(tmp_path, "executor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    v = pf.preflight(task_id="t", assignee="executor", lane="ready",
                     author_provider="anthropic",
                     home_resolver=resolver_for({"executor": home}))
    assert not any(f.code == "same_family_review" for f in v.findings)


def test_autoria_nao_medida_e_declarada_em_vez_de_silencio(tmp_path):
    """Sem provider de autoria, o veredito DIZ que nao mediu.

    Antes, ``author_provider=None`` produzia exatamente o mesmo silencio de uma
    revisao comprovadamente cruzada, e quem lesse concluiria "sem conflito de
    familia". Ausencia de medicao nao e ausencia de achado.
    """
    home = make_profile(tmp_path, "revisor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    v = pf.preflight(task_id="t", assignee="revisor", lane="review",
                     author_provider=None,
                     home_resolver=resolver_for({"revisor": home}))
    assert v.ok, "nao-medido nao pode parar a fila"
    nm = [f for f in v.findings if f.code == "author_family_not_measured"]
    assert len(nm) == 1
    assert nm[0].blocking is False
    assert "NOT MEASURED" in nm[0].message
    assert "Do not claim cross-family" in nm[0].next_action


def test_controle_negativo_autoria_medida_nao_emite_nao_medido(tmp_path):
    """O par do caso acima: medido de verdade, o aviso cala.

    Um aviso que acende sempre e tao inutil quanto um que nunca acende.
    """
    home = make_profile(tmp_path, "revisor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    for autor in ("openai-codex", "anthropic"):
        v = pf.preflight(task_id="t", assignee="revisor", lane="review",
                         author_provider=autor,
                         home_resolver=resolver_for({"revisor": home}))
        assert not any(f.code == "author_family_not_measured" for f in v.findings), autor


def test_nao_medido_nao_polui_a_lane_ready(tmp_path):
    """A lane ready nao tem autoria para medir; avisar ali seria ruido."""
    home = make_profile(tmp_path, "executor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    v = pf.preflight(task_id="t", assignee="executor", lane="ready",
                     home_resolver=resolver_for({"executor": home}))
    assert not any(f.code == "author_family_not_measured" for f in v.findings)


# --------------------------------------------------------------------------
# Extracao do provider da AUTORIA a partir do metadata que os workers gravam
# --------------------------------------------------------------------------

def test_provider_em_texto_livre_le_os_formatos_reais_do_board():
    """Formatos COPIADOS do kanban.db de producao (runs ja terminados).

    A versao anterior lia so ``metadata.provider``, presente em 1 de 315 runs
    com metadata; o resto grava a rota em texto livre e devolvia ``None``.
    """
    reais = {
        "gpt-6-astra/openai-codex": "openai-codex",
        "gpt-6-astra / openai-codex OAuth direto; sem wrappers": "openai-codex",
        "claude-opus-5 / anthropic, agente direto, OAuth assinatura": "anthropic",
        "claude-opus-5 nativo Hermes, sem wrapper ask-*/dev-*": None,
        "anthropic/claude-opus-5 OAuth assinatura": "anthropic",
    }
    for texto, esperado in reais.items():
        assert pf.provider_in_text(texto) == esperado, texto


def test_provider_em_texto_livre_nao_adivinha_por_nome_de_modelo():
    """``grok-4.6`` sozinho NAO vira provider.

    Adivinhar aqui seria trocar nao-medido por um palpite que depois viraria
    "familia verificada" no veredito.
    """
    assert pf.provider_in_text("grok-4.6") is None
    assert pf.provider_in_text("gpt-6-astra") is None
    assert pf.provider_in_text("") is None
    assert pf.provider_in_text(None) is None


def test_provider_em_texto_livre_prefere_o_nome_mais_longo():
    """``openai-codex`` nao pode ser lido como ``openai``: rotas e custos
    diferentes, ainda que a familia hoje coincida."""
    assert pf.provider_in_text("rota openai-codex") == "openai-codex"
    assert pf.provider_in_text("rota xai-oauth") == "xai-oauth"


def test_provider_em_texto_livre_respeita_fronteira_de_palavra():
    assert pf.provider_in_text("isso e inusual e nao cita provider") is None


@pytest.mark.parametrize("provider,familia", [
    ("openai-codex", "GPT"), ("anthropic", "Claude"), ("xai-oauth", "Grok"),
    ("google", "Gemini"), ("nous", "Hermes"), ("desconhecido", None), (None, None),
])
def test_familia_por_provider(provider, familia):
    assert pf.family_of(provider) == familia


# --------------------------------------------------------------------------
# Custo: o preflight NUNCA afirma cobertura financeira
# --------------------------------------------------------------------------

def test_nunca_afirma_cobertura_financeira_mesmo_no_caminho_feliz(tmp_path):
    home = make_profile(tmp_path, "executor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    v = pf.preflight(task_id="t", assignee="executor",
                     home_resolver=resolver_for({"executor": home}))
    assert v.ok
    cost = [f for f in v.findings if f.code == "cost_not_measured"]
    assert len(cost) == 1 and cost[0].blocking is False
    assert "NOT MEASURED" in cost[0].message


# --------------------------------------------------------------------------
# Segredo: o veredito nao pode carregar token
# --------------------------------------------------------------------------

@pytest.mark.parametrize("cenario", ["ok", "rate_limited", "auth_failed", "fallback", "paga"])
def test_nenhum_token_vaza_para_o_veredito(tmp_path, cenario):
    """Varre o JSON INTEIRO do veredito atras do segredo da fixture.

    Nao basta olhar os campos que eu lembrei de checar: serializa tudo e
    procura a string. Se um campo novo do upstream trouxer o token junto, este
    teste morre.
    """
    pools = {
        "ok": {"p": [oauth_ok()]},
        "rate_limited": {"p": [oauth_429()]},
        "auth_failed": {"p": [oauth_403()]},
        "fallback": {"p": [oauth_429()], "anthropic": [oauth_ok()]},
        "paga": {"p": [oauth_429()], "openrouter": [api_key_ok()]},
    }[cenario]
    fbs = {
        "fallback": [{"provider": "anthropic", "model": "claude-opus-5"}],
        "paga": [{"provider": "openrouter", "model": "m"}],
    }.get(cenario, [])
    home = make_profile(tmp_path, "executor", pool=pools, model="m", provider="p",
                        fallbacks=fbs)
    v = pf.preflight(task_id="t", assignee="executor",
                     home_resolver=resolver_for({"executor": home}))
    blob = json.dumps(v.as_dict())
    assert "SEGREDO-NAO-PODE-VAZAR" not in blob
    assert "sk-SEGREDO-PAGO" not in blob


def test_read_pool_status_nao_devolve_campo_de_token(tmp_path):
    home = make_profile(tmp_path, "executor", pool={"p": [oauth_ok()]})
    entries = pf.read_pool_status(home, "p")
    assert entries and "access_token" not in entries[0] and "refresh_token" not in entries[0]


def test_read_pool_status_distingue_ausente_de_vazio(tmp_path):
    home = tmp_path / "vazio"
    home.mkdir()
    assert pf.read_pool_status(home, "p") is None          # auth.json ausente
    (home / "auth.json").write_text(json.dumps({"credential_pool": {}}), encoding="utf-8")
    assert pf.read_pool_status(home, "p") == []            # lido, sem credencial


# --------------------------------------------------------------------------
# Custo de execucao: preflight nao pode gastar chamada de modelo
# --------------------------------------------------------------------------

def test_preflight_nao_faz_chamada_de_rede(tmp_path, monkeypatch):
    """Um preflight que gasta uma chamada por tick e pior que o defeito."""
    import socket

    def proibido(*a, **k):
        raise AssertionError("preflight tentou abrir socket")

    monkeypatch.setattr(socket.socket, "connect", proibido)
    monkeypatch.setattr(socket, "create_connection", proibido)
    home = make_profile(tmp_path, "executor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    v = pf.preflight(task_id="t", assignee="executor",
                     home_resolver=resolver_for({"executor": home}))
    assert v.ok


def test_preflight_e_rapido_o_bastante_para_rodar_por_tick(tmp_path):
    home = make_profile(tmp_path, "executor", pool={"anthropic": [oauth_ok()]},
                        model="claude-opus-5", provider="anthropic")
    res = resolver_for({"executor": home})
    inicio = time.monotonic()
    for _ in range(200):
        pf.preflight(task_id="t", assignee="executor", home_resolver=res)
    decorrido = time.monotonic() - inicio
    assert decorrido < 5.0, f"200 preflights levaram {decorrido:.2f}s"
