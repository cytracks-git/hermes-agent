"""Preflight de rota do perfil, antes de gastar um worker.

Card t_38817b72. Medido no board atlas (7 dias, 894 runs): 39 runs morreram numa
rota que já estava quebrada antes do dispatch — 27 com OAuth revogado (401) e 12
com modelo aposentado (404). Cada um consumiu um slot de worker, abriu e fechou
um run, e (quando classificado como crash) gastou o breaker do card por um
defeito que não é do card.

REGRA DE DESENHO — reprovar só com evidência POSITIVA de rota morta
-------------------------------------------------------------------
``check_route`` responde ``ok=False`` somente quando LEU no disco a prova de que
a rota não pode funcionar:

* ``revoked_credential`` — o próprio Hermes gravou ``last_auth_error`` com
  ``relogin_required`` para aquele provider (é a marca dos 401 medidos);
* ``expired_credential`` — há tokens, eles venceram e NÃO há ``refresh_token``;
* ``retired_model`` — o host declarou o modelo aposentado em ``retired_models.json``.

Tudo o mais autoriza. Em especial, **ausência de credencial NÃO é evidência**:
medido neste host, nenhum dos 4 perfis Anthropic tem entrada ``anthropic`` no
auth store — a assinatura é servida por fora — e mesmo assim eles rodam. Uma
versão anterior deste módulo reprovava por ausência e reprovou 5/5 perfis,
inclusive o que estava executando naquele instante: plugada no dispatcher,
teria parado o board inteiro. Preflight que reprova na dúvida é defeito maior
que o defeito que ele conserta.

CUSTO: este módulo NÃO faz chamada de rede. Lê o ``config.yaml`` do perfil e o
auth store local. Validar rota gastando uma chamada ao provider cobraria por
token a cada tick do dispatcher, que é exatamente o custo que não pode existir.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RouteVerdict:
    """Veredito do preflight. ``ok=True`` = pode despachar.

    ``kind``: ``ok`` | ``revoked_credential`` | ``expired_credential`` |
    ``retired_model`` | ``unknown`` (sem evidência — também autoriza).
    """

    ok: bool
    kind: str = "ok"
    reason: Optional[str] = None


_OK = RouteVerdict(True, "ok")
_UNKNOWN = RouteVerdict(True, "unknown")


def _hermes_home() -> Path:
    raw = os.environ.get("HERMES_HOME")
    if raw:
        return Path(raw)
    return Path.home() / ".hermes"


def _profile_dir(profile: str) -> Path:
    home = _hermes_home()
    if profile in ("", "default"):
        return home
    return home / "profiles" / profile


def _read_profile_route(profile: str) -> tuple[Optional[str], Optional[str]]:
    """``(provider, model)`` efetivos do perfil, sem inventar defaults.

    ``(None, None)`` quando nem arquivo nem camada gerenciada declaram rota — e isso
    vira ``unknown``, nunca reprovação.
    """
    from agent.secret_scope import (
        build_profile_secret_scope, reset_secret_scope, set_secret_scope,
    )
    from hermes_cli.config_effective import load_user_config_effective

    home = _profile_dir(profile)
    try:
        # O dispatcher lê outro perfil: expansão não pode usar o segredo do lançador.
        token = set_secret_scope(build_profile_secret_scope(home))
        try:
            data = load_user_config_effective(home / "config.yaml", fail_closed=True)
        finally:
            reset_secret_scope(token)
    except Exception:
        return (None, None)
    model = data.get("model") if isinstance(data, dict) else None
    if not isinstance(model, dict):
        return (None, None)
    provider = model.get("provider")
    name = model.get("default")
    return (
        provider if isinstance(provider, str) else None,
        name if isinstance(name, str) else None,
    )


def _read_auth_store(profile: str) -> Optional[dict]:
    """Auth store DO PERFIL, com recuo para o da home.

    Cada perfil tem o seu ``auth.json`` (medido neste host: executor, revisor,
    arquiteto e pesquisa têm um cada). Ler só o da home olharia para a
    credencial errada. ``None`` = ausente/ilegível = sem evidência.
    """
    for path in (_profile_dir(profile) / "auth.json", _hermes_home() / "auth.json"):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return None


def _provider_state(store: dict, provider: str) -> Optional[dict]:
    providers = store.get("providers")
    if not isinstance(providers, dict):
        return None
    state = providers.get(provider)
    return state if isinstance(state, dict) else None


def _revoked(state: dict) -> Optional[str]:
    """Mensagem do erro de auth que o próprio Hermes marcou como exigindo relogin.

    É a assinatura dos 401 medidos: ``last_auth_error.relogin_required``. Um
    erro de auth SEM esse marcador não basta — pode ter sido transitório e já
    superado.
    """
    err = state.get("last_auth_error")
    if not isinstance(err, dict) or not err.get("relogin_required"):
        return None
    msg = err.get("message") or err.get("code") or "relogin required"
    return str(msg)


def _has_tokens(state: dict) -> bool:
    """True quando há credencial materializada (achatada ou sob ``tokens``)."""
    tokens = state.get("tokens")
    if isinstance(tokens, dict) and any(
            tokens.get(k) for k in ("access_token", "api_key", "token")):
        return True
    return any(state.get(k) for k in ("access_token", "api_key", "token", "key"))


def _expired_beyond_refresh(state: dict) -> bool:
    """True só quando o token venceu E não há ``refresh_token`` para renovar.

    Vencido COM refresh é rotina de OAuth, não rota morta: o worker renova
    sozinho no startup. Tratar isso como quebra bloquearia todo perfil OAuth a
    cada expiração normal de token.
    """
    tokens = state.get("tokens")
    if not isinstance(tokens, dict):
        tokens = {}
    if state.get("refresh_token") or tokens.get("refresh_token"):
        return False
    raw = state.get("expires_at") or tokens.get("expires_at")
    if not raw:
        return False
    try:
        if isinstance(raw, (int, float)):
            expires = float(raw)
        else:
            expires = datetime.fromisoformat(str(raw)).timestamp()
    except Exception:
        return False  # não deu para ler: sem evidência
    return expires <= time.time()


def _retired_models(provider: str) -> set:
    """Modelos que o próprio host declara aposentados, em ``retired_models.json``.

    Ausente (o caso normal) = conjunto vazio = nenhum modelo declarado morto. O
    arquivo existe para o operador registrar um 404 já medido e parar de queimar
    runs nele até corrigir o config do perfil.
    """
    path = _hermes_home() / "retired_models.json"
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    entries = data.get(provider)
    return set(entries) if isinstance(entries, list) else set()


def check_route(profile: str) -> RouteVerdict:
    """Veredito de rota para ``profile``. Nunca levanta exceção.

    Roda dentro do tick do dispatcher: uma exceção aqui pararia o despacho de
    todos os cards, então toda falha interna vira ``_UNKNOWN`` (autoriza).
    """
    try:
        provider, model = _read_profile_route(profile)
        if not provider:
            return _UNKNOWN

        if model and model in _retired_models(provider):
            return RouteVerdict(
                False, "retired_model",
                f"modelo {model!r} do perfil {profile!r} está declarado aposentado "
                f"para o provider {provider!r} em retired_models.json — corrija a "
                f"rota do perfil antes de despachar",
            )

        store = _read_auth_store(profile)
        if store is None:
            return _UNKNOWN
        state = _provider_state(store, provider)
        if state is None:
            # Sem entrada para este provider: NÃO é prova de rota morta (a
            # assinatura pode ser servida por fora do store). Autoriza.
            return _UNKNOWN

        revogada = _revoked(state)
        if revogada:
            return RouteVerdict(
                False, "revoked_credential",
                f"credencial do provider {provider!r} (perfil {profile!r}) exige "
                f"novo login: {revogada}",
            )
        if _has_tokens(state) and _expired_beyond_refresh(state):
            return RouteVerdict(
                False, "expired_credential",
                f"credencial do provider {provider!r} (perfil {profile!r}) venceu e "
                f"não há refresh_token para renovar — reautentique antes de despachar",
            )
        return _OK
    except Exception:
        logger.debug("route preflight falhou para %s; autorizando", profile, exc_info=True)
        return _UNKNOWN


# O loader oficial já cacheia parse por arquivo, overlay e referências de env.
# O agrupamento usa as rotas efetivas: mtime só do YAML perderia mudanças de .env
# e de política gerenciada sem edição do arquivo do perfil.
_quota_cache: dict = {"key": None, "value": None}


def _quota_cache_key() -> tuple:
    """``(home, ((perfil, rota_efetiva), ...))`` — o que invalida a medição."""
    home = _hermes_home()
    itens: list = []
    perfis = ["default"]
    root = home / "profiles"
    if root.is_dir():
        perfis += sorted(p.name for p in root.iterdir() if p.is_dir())
    for perfil in perfis:
        itens.append((perfil, _read_profile_route(perfil)))
    return (str(home), tuple(itens))


def shared_quota_groups(*, use_cache: bool = True) -> dict:
    """``{provider: [perfis]}`` para providers com MAIS DE UM perfil apontado.

    Item 4 do card t_38817b72: cota compartilhada é invisível hoje. Medido neste
    host: 4 dos 5 perfis (default, arquiteto, executor, pesquisa) apontam para a
    MESMA assinatura ``anthropic``, enquanto ``max_in_progress: 4`` promete 4
    workers paralelos. Na prática disputam um único teto de cota — os 429 se
    concentram no horário de pico, assinatura de concorrência, não de volume. O
    resultado é fila com cara de paralelismo.

    Só relata a configuração efetiva: provider com um perfil só não aparece.

    ``use_cache=False`` refaz o agrupamento; o loader oficial mantém seu cache
    de configuração com invalidação por arquivo, overlay e referências de env.
    """
    key = _quota_cache_key()
    if use_cache and _quota_cache["value"] is not None and _quota_cache["key"] == key:
        return dict(_quota_cache["value"])
    grupos: dict = {}
    try:
        for perfil, (provider, _model) in key[1]:
            if provider:
                grupos.setdefault(provider, []).append(perfil)
    except Exception:
        logger.debug("shared_quota_groups falhou", exc_info=True)
        return {}
    compartilhados = {prov: nomes for prov, nomes in grupos.items() if len(nomes) > 1}
    _quota_cache["value"] = compartilhados
    _quota_cache["key"] = key
    return dict(compartilhados)


def describe_shared_quota(grupos: dict) -> str:
    """Uma linha para o operador, ou ``""`` quando ninguém compartilha.

    ``anthropic=4 profiles (arquiteto, default, executor, pesquisa)`` — formato
    estável para o tick do CLI e o warn de dispatcher parado. Texto em inglês:
    é superfície que o operador lê (regra 12-G).
    """
    if not isinstance(grupos, dict) or not grupos:
        return ""
    partes = []
    for prov in sorted(grupos):
        nomes = grupos[prov]
        if not isinstance(nomes, list) or len(nomes) < 2:
            continue
        partes.append(f"{prov}={len(nomes)} profiles ({', '.join(sorted(nomes))})")
    return "; ".join(partes)
