"""Preflight verificavel de papel, autenticacao e rota ANTES do despacho.

Por que este modulo existe (medido no board atlas em 2026-09-19):

  CASO A -- t_abceecc5 run289: spawn 07:33, blocked 07:35. O worker gastou uma
  chamada de modelo para descobrir, DENTRO do prompt, que a politica do perfil
  nao permitia executar.

  CASO B -- t_abceecc5 run290: spawn 07:38, CRASHED 07:44 com
  `HTTP 429: The usage limit has been reached`. A condicao era verificavel ANTES
  do spawn: `hermes -p revisor auth list` ja mostrava a credencial do provider
  solicitado carimbada `rate-limited usage_limit_reached (429) (6d 8h left)` e
  `fallback_providers` vazio.

A licao das duas: verificacao escrita no prompt do worker chega TARDE -- a
primeira chamada ao modelo ja aconteceu. O preflight roda no dispatcher, antes
do `Popen`, lendo apenas estado local (SQLite + arquivos do perfil alvo).

LIMITES DECLARADOS, nao escondidos:

  * Le CARIMBO local, nao servico remoto. `rate-limited` nao e `revoked`, e
    ausencia de carimbo nao prova que a proxima chamada vai passar.
  * NAO mede cobertura financeira. OAuth logado nao e fatura paga; este modulo
    nunca afirma elegibilidade de custo.
  * NAO copia segredo: apenas os campos de ``_STATUS_FIELDS`` saem do auth.json.
    O token nunca entra no veredito (provado em bateria).
  * Familia igual entre autoria e revisao e DECLARADA, nunca bloqueada -- o H1
    aceita mesma familia para nao represar a fila, desde que o parecer diga.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# Campos do auth.json que o preflight pode ler. Um allowlist, nao um denylist:
# campo novo do upstream nasce FORA do veredito, nunca dentro dele por descuido.
# `access_token` / `refresh_token` estao ausentes de proposito.
_STATUS_FIELDS = (
    "id", "label", "auth_type", "priority", "source",
    "last_status", "last_status_at", "last_error_code",
    "last_error_reason", "last_error_message", "last_error_reset_at",
    "failure_reason",
)

# Familia de MODELO por provider. Serve a independencia autor/revisor
# (SDD-MUST-611): dois provedores da mesma familia nao sao revisao cruzada.
_PROVIDER_FAMILY = {
    "openai-codex": "GPT",
    "openai": "GPT",
    "azure-openai": "GPT",
    "anthropic": "Claude",
    "anthropic-vertex": "Claude",
    "xai": "Grok",
    "xai-oauth": "Grok",
    "google": "Gemini",
    "gemini": "Gemini",
    "google-vertex": "Gemini",
    "nous": "Hermes",
}

# Estados de credencial. Sao decisoes DIFERENTES, nao sinonimos de "sem auth":
# tratar os tres como um so produz o falso-bloqueio que ja prendeu cards reais.
STATE_USABLE = "usable"              # sem carimbo, ou carimbo ja expirado
STATE_RATE_LIMITED = "rate_limited"  # 429 com janela futura declarada
STATE_AUTH_FAILED = "auth_failed"    # 401/403 -- re-login, esperar nao resolve
STATE_DEAD = "dead"                  # terminal upstream (revogado/invalidado)
STATE_EXHAUSTED = "exhausted"        # esgotado sem janela legivel

_UNUSABLE = (STATE_RATE_LIMITED, STATE_AUTH_FAILED, STATE_DEAD, STATE_EXHAUSTED)


@dataclass(frozen=True)
class Finding:
    """Um fato verificavel sobre o despacho. ``blocking`` decide o veredito.

    ``message`` e ``next_action`` sao lidos por um operador humano, logo em
    INGLES (12-G); comentario e docstring deste arquivo, em pt-BR.
    """

    code: str
    blocking: bool
    message: str
    next_action: str = ""

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "blocking": self.blocking,
            "message": self.message,
            "next_action": self.next_action,
        }


@dataclass(frozen=True)
class Verdict:
    task_id: str
    assignee: str
    findings: tuple = field(default_factory=tuple)
    route: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not any(f.blocking for f in self.findings)

    @property
    def blocking(self) -> tuple:
        return tuple(f for f in self.findings if f.blocking)

    def as_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "assignee": self.assignee,
            "ok": self.ok,
            "findings": [f.as_dict() for f in self.findings],
            "route": dict(self.route),
        }

    def reason(self) -> str:
        """Uma linha por bloqueio, com a proxima acao. Vazio quando passa."""
        return " | ".join(
            f"{f.message} -> {f.next_action}" if f.next_action else f.message
            for f in self.blocking
        )


# --------------------------------------------------------------------------
# Leitura do perfil ALVO (nunca do perfil ativo)
# --------------------------------------------------------------------------

def profile_home(name: str) -> Optional[Path]:
    """HERMES_HOME do perfil, ou None quando o nome nao resolve.

    Delega a ``hermes_cli.profiles`` porque ``default`` NAO e
    ``profiles/default``: e o proprio HERMES_HOME. Reimplementar isso aqui
    inventaria um diretorio que nao existe e reprovaria o perfil default.
    """
    try:
        from hermes_cli.profiles import get_profile_dir, profile_exists
    except Exception:
        return None
    try:
        if not profile_exists(name):
            return None
        return Path(get_profile_dir(name))
    except Exception:
        return None


def _read_json(path: Path) -> Optional[dict]:
    """``None`` distingue ausente/ilegivel de ``{}`` legitimamente vazio.

    ``exists()`` sozinho nao separa AUSENTE de PRESENTE-E-ILEGIVEL, e e assim
    que vacuidade vira verde: um EACCES leria como "perfil sem credencial".
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def read_pool_status(home: Path, provider: str) -> Optional[list]:
    """Entradas do pool do provider, SEM SEGREDO -- so ``_STATUS_FIELDS``.

    ``None`` = auth.json ausente ou ilegivel (nao medido).
    ``[]``   = arquivo lido e o provider nao tem credencial ali.
    """
    store = _read_json(home / "auth.json")
    if store is None:
        return None
    pool = store.get("credential_pool")
    if not isinstance(pool, dict):
        return []
    entries = pool.get(provider)
    if not isinstance(entries, list):
        return []
    return [
        {k: e.get(k) for k in _STATUS_FIELDS if k in e}
        for e in entries
        if isinstance(e, dict)
    ]


def read_route(home: Path) -> dict:
    """``model``/``provider``/``fallbacks`` do config.yaml do perfil alvo."""
    path = home / "config.yaml"
    try:
        import yaml
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    model_cfg = raw.get("model")
    model = provider = None
    if isinstance(model_cfg, str):
        model = model_cfg
    elif isinstance(model_cfg, dict):
        model = model_cfg.get("default") or model_cfg.get("model")
        provider = model_cfg.get("provider")
    fallbacks = []
    for entry in raw.get("fallback_providers") or []:
        if not isinstance(entry, dict):
            continue
        # `enabled` ausente conta como habilitado: e assim que o Hermes trata a
        # lista, e um preflight mais rigoroso que o motor recusaria rota viva.
        if entry.get("enabled") is False:
            continue
        fallbacks.append({
            "provider": entry.get("provider"),
            "model": entry.get("model"),
        })
    return {"model": model, "provider": provider, "fallbacks": fallbacks}


# --------------------------------------------------------------------------
# Estado de uma credencial
# --------------------------------------------------------------------------

def credential_state(entry: dict, now: Optional[float] = None) -> tuple:
    """``(estado, segundos_restantes)`` de UMA entrada do pool.

    Reusa o classificador e a janela canonicos do Hermes
    (``auth_commands._classify_exhausted_status`` e
    ``credential_pool._exhausted_until``) em vez de imitar a heuristica deles:
    um proxy diverge do motor em silencio na primeira mudanca upstream.

    ``PooledCredential.from_dict`` e construido SEM token -- as duas funcoes so
    leem campos de status, entao o segredo nunca precisa ser carregado.
    """
    now = time.time() if now is None else now
    status = entry.get("last_status")
    if status == STATE_DEAD:
        return STATE_DEAD, None
    if status != "exhausted":
        return STATE_USABLE, None
    try:
        from agent.credential_pool import PooledCredential, _exhausted_until
        from hermes_cli.auth_commands import _classify_exhausted_status
    except Exception:
        # Sem as funcoes canonicas o estado e NAO MEDIDO, e nao-medido nao pode
        # virar "usable": isso reabriria exatamente o CASO B.
        return STATE_EXHAUSTED, None
    cred = PooledCredential.from_dict(entry.get("provider") or "", dict(entry))
    label, _show_window = _classify_exhausted_status(cred)
    until = _exhausted_until(cred)
    remaining = None if until is None else max(0, int(until - now))
    if label == "auth failed":
        return STATE_AUTH_FAILED, None
    if remaining is not None and remaining <= 0:
        # `exhausted (ready to retry)` -- a janela passou, a rota volta a ser
        # candidata. Tratar como bloqueio seria o falso-bloqueio do B3.
        return STATE_USABLE, 0
    if label == "rate-limited":
        return STATE_RATE_LIMITED, remaining
    return STATE_EXHAUSTED, remaining


def provider_is_available(home: Path, provider: str, now: Optional[float] = None) -> tuple:
    """``(disponivel, detalhe)`` para um provider dentro de UM perfil.

    ``disponivel`` e ``None`` quando nao deu para medir (auth.json ilegivel):
    o chamador declara NAO MEDIDO em vez de escolher o adjetivo confortavel.
    """
    entries = read_pool_status(home, provider)
    if entries is None:
        return None, {"provider": provider, "reason": "auth_store_unreadable"}
    if not entries:
        return False, {"provider": provider, "reason": "no_credential"}
    worst = []
    for entry in entries:
        state, remaining = credential_state({**entry, "provider": provider}, now=now)
        if state == STATE_USABLE:
            return True, {"provider": provider, "reason": "usable", "id": entry.get("id")}
        worst.append({"id": entry.get("id"), "state": state, "retry_in_seconds": remaining})
    return False, {"provider": provider, "reason": "all_unusable", "credentials": worst}


def family_of(provider: Optional[str]) -> Optional[str]:
    if not provider:
        return None
    return _PROVIDER_FAMILY.get(str(provider).strip().lower())


def _pool_auth_types(home: Path, provider: Optional[str]) -> set:
    """Tipos de autenticacao presentes no pool do provider (``oauth``/``api_key``).

    Conjunto VAZIO quando nao ha entrada ou o store nao pode ser lido -- e por
    isso o chamador compara com ``== {"api_key"}``: nao-medido nunca satisfaz a
    igualdade, entao a ausencia de medicao jamais vira acusacao de rota paga.
    """
    entries = read_pool_status(home, (provider or "").strip())
    if not entries:
        return set()
    return {str(e.get("auth_type") or "").strip().lower() or "api_key" for e in entries}


# --------------------------------------------------------------------------
# Veredito
# --------------------------------------------------------------------------

def _fmt_window(seconds: Optional[int]) -> str:
    if seconds is None:
        return "no declared window"
    minutes, sec = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    for value, unit in ((days, "d"), (hours, "h"), (minutes, "m"), (sec, "s")):
        if value:
            return f"{value}{unit} left"
    return "ready to retry"


def preflight(
    *,
    task_id: str,
    assignee: Optional[str],
    requested_model: Optional[str] = None,
    requested_provider: Optional[str] = None,
    author_provider: Optional[str] = None,
    lane: str = "ready",
    now: Optional[float] = None,
    home_resolver=None,
) -> Verdict:
    """Decide, SEM chamar modelo, se este despacho pode acontecer.

    ``author_provider`` e o provider que produziu a entrega sob revisao; ele so
    alimenta a DECLARACAO de familia (nunca um bloqueio).

    ``home_resolver`` e resolvido AQUI, e nao como default no ``def``: um
    default ligado na definicao congela a funcao do momento do import e torna o
    modulo impossivel de isolar em teste (e de redirecionar em runtime) -- o
    valor injetado seria silenciosamente ignorado.
    """
    home_resolver = profile_home if home_resolver is None else home_resolver
    now = time.time() if now is None else now
    findings: list = []
    route: dict = {
        "requested_model": requested_model,
        "requested_provider": requested_provider,
        "lane": lane,
    }

    name = (assignee or "").strip()
    if not name:
        findings.append(Finding(
            "assignee_missing", True,
            "Task has no assignee, so no profile can be resolved.",
            "Assign a real Hermes profile to this task.",
        ))
        return Verdict(task_id, "", tuple(findings), route)

    home = home_resolver(name)
    if home is None:
        findings.append(Finding(
            "profile_missing", True,
            f"Assignee '{name}' does not resolve to a live Hermes profile.",
            "Fix the assignee: run `hermes profile list` and use an existing name.",
        ))
        return Verdict(task_id, name, tuple(findings), route)
    route["profile_home"] = str(home)

    configured = read_route(home)
    route["configured_model"] = configured.get("model")
    route["configured_provider"] = configured.get("provider")

    provider = (requested_provider or configured.get("provider") or "").strip()
    model = requested_model or configured.get("model")
    route["effective_provider"] = provider or None
    route["effective_model"] = model
    if not provider:
        findings.append(Finding(
            "provider_unresolved", True,
            f"Profile '{name}' declares no provider and the task requests none.",
            f"Set a provider: `hermes -p {name} config set model.provider <provider>`.",
        ))
        return Verdict(task_id, name, tuple(findings), route)

    available, detail = provider_is_available(home, provider, now=now)
    route["primary"] = detail

    if available is None:
        findings.append(Finding(
            "auth_not_measured", True,
            f"Cannot read the credential store of profile '{name}': auth state NOT MEASURED.",
            f"Check that {home / 'auth.json'} exists and is readable, then retry.",
        ))
        return Verdict(task_id, name, tuple(findings), route)

    if not available:
        # Antes de bloquear, ver se ha fallback habilitado com rota viva. Usar o
        # fallback NAO e downgrade silencioso: o modelo efetivo e anunciado.
        chosen = None
        checked = []
        for fb in configured.get("fallbacks") or []:
            fb_provider = (fb.get("provider") or "").strip()
            if not fb_provider:
                continue
            fb_ok, fb_detail = provider_is_available(home, fb_provider, now=now)
            checked.append(fb_detail)
            if fb_ok:
                chosen = fb
                break
        route["fallbacks_checked"] = checked

        if chosen is not None:
            fb_provider = chosen.get("provider")
            # Fallback PAGO por token e o unico caso em que a rota paga e
            # escolhida SEM um humano no meio -- e e exatamente o "fallback
            # pago silencioso" que a regra de custo proibe. A rota primaria
            # por chave e escolha registrada do operador: declarada, nao
            # bloqueada, senao o preflight derruba perfis legitimos.
            if _pool_auth_types(home, fb_provider) == {"api_key"}:
                findings.append(Finding(
                    "paid_fallback_refused", True,
                    f"Requested provider '{provider}' is unusable and the only usable "
                    f"fallback '{fb_provider}' authenticates by API key (per-token "
                    f"billing), which this board does not allow as an automatic route.",
                    "Route the task to a subscription/OAuth provider, or have the operator "
                    "authorise the paid route explicitly.",
                ))
                return Verdict(task_id, name, tuple(findings), route)
            route["effective_provider"] = fb_provider
            route["effective_model"] = chosen.get("model") or model
            findings.append(Finding(
                "route_fallback", False,
                f"Requested provider '{provider}' is unusable; dispatching on declared "
                f"fallback '{fb_provider}' with model "
                f"'{route['effective_model']}'.",
                "Announce the effective model in the handoff; this is not a silent downgrade.",
            ))
        else:
            if detail.get("reason") == "no_credential":
                findings.append(Finding(
                    "auth_missing", True,
                    f"Profile '{name}' has no credential for provider '{provider}'.",
                    f"Authenticate it: `hermes -p {name} auth add {provider}`.",
                ))
            else:
                worst = (detail.get("credentials") or [{}])[0]
                state = worst.get("state")
                window = _fmt_window(worst.get("retry_in_seconds"))
                if state == STATE_AUTH_FAILED:
                    action = f"Re-authenticate: `hermes -p {name} auth add {provider}`. Waiting will not help."
                elif state == STATE_DEAD:
                    action = f"Credential is terminally invalid; re-login: `hermes -p {name} auth add {provider}`."
                else:
                    action = (
                        f"Wait for the quota window ({window}) or route this task to an "
                        f"eligible provider; no enabled fallback is usable."
                    )
                findings.append(Finding(
                    "auth_unusable", True,
                    f"Every credential of provider '{provider}' in profile '{name}' is "
                    f"unusable (state={state}, {window}), and no enabled fallback is usable.",
                    action,
                ))
            return Verdict(task_id, name, tuple(findings), route)

    # Independencia de familia: DECLARACAO, nunca bloqueio. O H1 aceita mesma
    # familia para nao represar a fila -- o que ele proibe e chamar isso de
    # revisao cruzada.
    eff_family = family_of(route.get("effective_provider"))
    author_family = family_of(author_provider)
    route["effective_family"] = eff_family
    route["author_family"] = author_family
    if lane == "review" and author_family and eff_family and author_family == eff_family:
        findings.append(Finding(
            "same_family_review", False,
            f"Review route is the same model family as the authoring route "
            f"({eff_family}); this is NOT cross-family review.",
            "State this condition explicitly in the review verdict.",
        ))

    # Cobertura financeira nunca e afirmada aqui, e dizer isso e parte do
    # veredito: carimbo local ausente nao prova cota nem fatura.
    findings.append(Finding(
        "cost_not_measured", False,
        "Cost and remaining quota are NOT MEASURED: this preflight reads local "
        "credential stamps only, never the provider's billing state.",
        "",
    ))
    return Verdict(task_id, name, tuple(findings), route)
