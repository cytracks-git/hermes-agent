"""Preflight de rota: não despachar card para morrer em credencial/modelo já quebrado.

Card t_38817b72. Medido no board atlas (7 dias, 894 runs): 27 runs morreram com
OAuth revogado (401) e 12 com modelo aposentado (404) — 39 runs queimados numa
rota que já estava podre ANTES do dispatch. Cada um desses gastou um slot de
worker, um run e (quando classificado como crash) uma unidade do breaker do card.

Regra de desenho provada aqui: o preflight só reprova com EVIDÊNCIA POSITIVA de
rota morta. Sem evidência — arquivo de auth ausente, provider desconhecido,
qualquer erro de leitura — ele AUTORIZA o dispatch. Um preflight que reprova na
dúvida para o board inteiro, e seria um defeito pior que o que ele conserta.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from hermes_cli import kanban_route_preflight as rp


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / ".hermes"
    (h / "profiles").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(h))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return h


def _profile(home: Path, name: str, *, provider: str, model: str) -> None:
    d = home / "profiles" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "config.yaml").write_text(
        f"model:\n  provider: {provider}\n  default: {model}\n", encoding="utf-8")


def _auth(home: Path, store: dict, *, profile: str | None = None) -> None:
    """Auth store do perfil (o caso real) ou, sem ``profile``, o da home."""
    base = home / "profiles" / profile if profile else home
    base.mkdir(parents=True, exist_ok=True)
    (base / "auth.json").write_text(json.dumps(store), encoding="utf-8")


_FUTURE = "2099-01-01T00:00:00+00:00"
_PAST = "2020-01-01T00:00:00+00:00"


# ---------------------------------------------------------------------------
# CONTROLE POSITIVO — rota sadia despacha
# ---------------------------------------------------------------------------


def test_rota_sadia_autoriza_dispatch(home):
    """Credencial presente e válida: o preflight NÃO pode atrapalhar."""
    _profile(home, "executor", provider="anthropic", model="claude-opus-5")
    _auth(home, {"providers": {"anthropic": {
        "access_token": "tok", "expires_at": _FUTURE}}}, profile="executor")

    verdict = rp.check_route("executor")
    assert verdict.ok is True, f"rota sadia reprovada: {verdict.reason}"
    assert verdict.reason is None


def test_api_key_sem_expiracao_autoriza(home):
    """Credencial de chave (sem ``expires_at``) é válida — não inventar expiração."""
    _profile(home, "executor", provider="anthropic", model="claude-opus-5")
    _auth(home, {"providers": {"anthropic": {"api_key": "sk-abc"}}}, profile="executor")

    assert rp.check_route("executor").ok is True


def test_credencial_do_PERFIL_e_nao_da_home(home):
    """O store do perfil manda: cada perfil tem o seu ``auth.json``.

    Medido neste host: executor, revisor, arquiteto e pesquisa têm um cada. Ler
    só o da home olharia para a credencial de outro perfil.
    """
    _profile(home, "executor", provider="xai-oauth", model="grok-4.6")
    # home diz revogado; o perfil diz saudável — vence o do perfil.
    _auth(home, {"providers": {"xai-oauth": {
        "last_auth_error": {"relogin_required": True, "message": "velho"}}}})
    _auth(home, {"providers": {"xai-oauth": {"tokens": {"access_token": "t"}}}},
          profile="executor")

    assert rp.check_route("executor").ok is True


# ---------------------------------------------------------------------------
# CONTROLE NEGATIVO — rota comprovadamente morta reprova
# ---------------------------------------------------------------------------


def test_credencial_revogada_reprova(home):
    """Os 27 runs de 401: o próprio Hermes marcou ``relogin_required``."""
    _profile(home, "executor", provider="openai-codex", model="gpt-5")
    _auth(home, {"providers": {"openai-codex": {
        "tokens": {},
        "last_auth_error": {
            "code": "refresh_token_reused", "relogin_required": True,
            "message": "Codex refresh token was already consumed"}}}},
        profile="executor")

    verdict = rp.check_route("executor")
    assert verdict.ok is False, "credencial revogada foi autorizada a despachar"
    assert verdict.kind == "revoked_credential"
    assert "Codex refresh token" in (verdict.reason or "")


def test_erro_de_auth_sem_relogin_autoriza(home):
    """Erro de auth transitório (sem ``relogin_required``) NÃO é rota morta.

    Sem esta distinção, um 429 antigo gravado como erro de auth bloquearia o
    perfil para sempre.
    """
    _profile(home, "executor", provider="openai-codex", model="gpt-5")
    _auth(home, {"providers": {"openai-codex": {
        "tokens": {"access_token": "t"},
        "last_auth_error": {"code": "temporarily_unavailable"}}}},
        profile="executor")

    assert rp.check_route("executor").ok is True


def test_token_expirado_sem_refresh_reprova(home):
    """Token vencido e SEM refresh_token: nada no host consegue renovar."""
    _profile(home, "executor", provider="anthropic", model="claude-opus-5")
    _auth(home, {"providers": {"anthropic": {
        "access_token": "velho", "expires_at": _PAST}}}, profile="executor")

    verdict = rp.check_route("executor")
    assert verdict.ok is False, "token vencido irrecuperável foi autorizado"
    assert verdict.kind == "expired_credential"


def test_token_expirado_COM_refresh_autoriza(home):
    """Vencido mas renovável não é rota morta — o worker renova sozinho.

    Sem esta distinção o preflight bloquearia todo perfil OAuth a cada expiração
    normal de token, que é rotina, não defeito.
    """
    _profile(home, "executor", provider="anthropic", model="claude-opus-5")
    _auth(home, {"providers": {"anthropic": {
        "access_token": "velho", "refresh_token": "r", "expires_at": _PAST}}},
        profile="executor")

    assert rp.check_route("executor").ok is True


def test_modelo_aposentado_reprova(home):
    """Os 12 runs de 404: modelo na lista de aposentados do próprio host."""
    _profile(home, "executor", provider="anthropic", model="claude-opus-4")
    _auth(home, {"providers": {"anthropic": {"api_key": "sk"}}}, profile="executor")
    (home / "retired_models.json").write_text(
        json.dumps({"anthropic": ["claude-opus-4"]}), encoding="utf-8")

    verdict = rp.check_route("executor")
    assert verdict.ok is False, "modelo aposentado foi autorizado a despachar"
    assert verdict.kind == "retired_model"
    assert "claude-opus-4" in (verdict.reason or "")


# ---------------------------------------------------------------------------
# FAIL-OPEN — sem evidência, não atrapalha
# ---------------------------------------------------------------------------


def test_provider_ausente_no_store_autoriza(home):
    """REGRESSÃO do falso positivo que este módulo já teve.

    Medido no host real: nenhum dos 4 perfis Anthropic tem entrada ``anthropic``
    no auth store (a assinatura é servida por fora) — e todos rodam. A versão
    que reprovava por ausência devolveu ``ok=False`` para 5/5 perfis, incluindo
    o que estava executando; plugada no dispatcher, pararia o board inteiro.
    """
    _profile(home, "executor", provider="anthropic", model="claude-opus-5")
    _auth(home, {"providers": {"xai-oauth": {"access_token": "outro"}}},
          profile="executor")

    verdict = rp.check_route("executor")
    assert verdict.ok is True, (
        "ausência de credencial tratada como prova de rota morta — "
        f"pararia o board ({verdict.reason})")
    assert verdict.kind == "unknown"


@pytest.mark.parametrize("cenario", ["sem_auth_json", "auth_corrompido", "sem_config"])
def test_sem_evidencia_autoriza(home, cenario):
    """Na dúvida o preflight autoriza. Reprovar sem evidência pararia o board."""
    if cenario != "sem_config":
        _profile(home, "executor", provider="anthropic", model="claude-opus-5")
    if cenario == "auth_corrompido":
        (home / "profiles" / "executor" / "auth.json").write_text(
            "{nao é json", encoding="utf-8")

    verdict = rp.check_route("executor")
    assert verdict.ok is True, (
        f"{cenario}: preflight reprovou sem evidência de rota morta "
        f"({verdict.reason})")


def test_provider_desconhecido_autoriza(home):
    """Provider fora do catálogo conhecido: não é prova de que está quebrado."""
    _profile(home, "executor", provider="provider-novo-qualquer", model="m")
    _auth(home, {"providers": {}}, profile="executor")

    assert rp.check_route("executor").ok is True


def test_nunca_levanta_excecao(home, monkeypatch):
    """O preflight roda dentro do tick do dispatcher: exceção dele pararia o board.

    NEGATIVO da robustez: sabotar a leitura interna e exigir que ele ainda
    devolva 'pode despachar' em vez de propagar.
    """
    _profile(home, "executor", provider="anthropic", model="claude-opus-5")

    def _explode(*a, **k):
        raise RuntimeError("disco pegou fogo")

    monkeypatch.setattr(rp, "_read_profile_route", _explode)
    verdict = rp.check_route("executor")
    assert verdict.ok is True
    assert verdict.kind == "unknown"


# ---------------------------------------------------------------------------
# Item 4 — cota compartilhada visível
# ---------------------------------------------------------------------------


def test_cota_compartilhada_aparece(home):
    """NEGATIVO: N perfis na mesma assinatura têm de ser reportados.

    É a configuração medida no board atlas: 4 perfis, 1 assinatura, e
    ``max_in_progress: 4`` prometendo paralelismo que a cota não entrega.
    """
    for nome in ("executor", "pesquisa", "arquiteto"):
        _profile(home, nome, provider="anthropic", model="claude-opus-5")
    _profile(home, "revisor", provider="xai-oauth", model="grok-4.6")

    grupos = rp.shared_quota_groups()

    assert "anthropic" in grupos, f"cota compartilhada invisível: {grupos}"
    assert set(grupos["anthropic"]) == {"executor", "pesquisa", "arquiteto"}
    assert "xai-oauth" not in grupos, "provider com 1 perfil não é compartilhado"


def test_sem_compartilhamento_nao_inventa_alarme(home):
    """POSITIVO: cada perfil na sua assinatura — nada a reportar.

    Um detector que reportasse sempre seria ruído, e ruído é ignorado.
    """
    _profile(home, "executor", provider="anthropic", model="claude-opus-5")
    _profile(home, "revisor", provider="xai-oauth", model="grok-4.6")

    assert rp.shared_quota_groups() == {}
