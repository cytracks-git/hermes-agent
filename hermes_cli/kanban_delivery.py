"""Delivery dimension for kanban cards (orthogonal to execution status).

Classifies already-collected facts. Does not talk to GitHub. OPEN+CI is never
Integrated. Done is not rewritten. NULL delivery columns mean unknown.
"""
from __future__ import annotations

REQUIRES = frozenset({"requires_main", "requires_install"})
LOCAL_PHASES = frozenset({
    "inventario", "desenho", "analise", "spike", "auditoria", "plano", "revisao_de_plano",
})
PROHIBITED = (
    "admin_bypass",
    "force_push",
    "guards_off",
    "updater_off",
    "synthetic_h1",
    "mass_draft",
)

_EMPTY = {
    "delivery": "unknown",
    "complete_ok": False,
    "counts_as_integrated": False,
    "counts_as_delivered": False,
    "auto_merge_allowed": False,
    "recorded_refusal": False,
    "error_visible": False,
    "error_swallowed": False,
    "github_calls_expected": None,
    "duplicate_action": False,
    "second_post": False,
    "next_action": "",
}


def verdict(facts: dict) -> dict:
    """Same contract as the frozen oracle (desenho a4edf2f456)."""
    out = dict(_EMPTY)
    applicability = facts.get("applicability") or "unknown"

    if facts.get("retry_after_crash") and facts.get("prior_action_applied"):
        out.update(
            delivery=facts.get("delivery_before") or "unknown",
            complete_ok=True,
            duplicate_action=False,
            second_post=False,
            next_action="noop mesma chave (task_id, accepted_sha, transition)",
        )
        _apply_counts(out)
        return out

    for flag in PROHIBITED:
        if facts.get(flag):
            out.update(
                delivery=facts.get("delivery_before") or "reviewed",
                recorded_refusal=True,
                error_visible=True,
                auto_merge_allowed=False,
                next_action=f"recusa CISO registrada: {flag}",
            )
            _apply_counts(out)
            return out

    if facts.get("claim_verified_from_merge_only"):
        out.update(
            delivery="integrated",
            recorded_refusal=True,
            error_visible=True,
            next_action="recusa: merge ≠ deploy; falta installed+verified",
        )
        _apply_counts(out)
        return out

    if facts.get("summary_as_proof") or facts.get("executor_summary_as_review"):
        out.update(
            delivery=facts.get("delivery_before") or "unknown",
            recorded_refusal=True,
            error_visible=True,
            next_action="prova recusada: summary autoral não conta",
        )
        _apply_counts(out)
        return out

    if facts.get("github_error"):
        previous = facts.get("delivery_before")
        delivery = "unknown"
        if previous and previous not in {"n/a"}:
            delivery = previous
        if applicability in REQUIRES and delivery == "n/a":
            delivery = "unknown"
        out.update(
            delivery=delivery,
            error_visible=True,
            error_swallowed=False,
            next_action="chip error/unknown; medir de novo; não inferir",
        )
        _apply_counts(out)
        return out

    if facts.get("second_dispatcher"):
        out.update(
            recorded_refusal=True,
            error_visible=True,
            next_action="recusa: um dispatcher por máquina",
        )
        _apply_counts(out)
        return out

    if applicability == "local_phase":
        if facts.get("require_main"):
            out.update(
                delivery="n/a",
                recorded_refusal=True,
                error_visible=True,
                next_action="defeito: exigir main em local_phase",
            )
            _apply_counts(out)
            return out
        out.update(
            delivery="n/a",
            complete_ok=True,
            github_calls_expected=0,
            next_action="fase local encerrada",
        )
        _apply_counts(out)
        return out

    if applicability == "superseded":
        out.update(delivery="n/a", complete_ok=True, next_action="nada")
        _apply_counts(out)
        return out

    if applicability == "unknown":
        out.update(
            delivery="n/a",
            complete_ok=False,
            next_action="medir; não inferir; não completar como entregável",
        )
        _apply_counts(out)
        return out

    if facts.get("completion_contract") in (None, "") and applicability in REQUIRES:
        out.update(
            delivery="unknown",
            complete_ok=False,
            next_action="NULL legado: unknown até recodificar",
        )
        _apply_counts(out)
        return out

    accepted = facts.get("accepted_sha")
    head = facts.get("head_sha")
    if accepted and head and accepted != head:
        out.update(
            delivery="invalidated",
            complete_ok=True,
            next_action=f"re-review SHA {head}; Rel congela de novo",
        )
        _apply_counts(out)
        return out

    if facts.get("merge_reverted"):
        out.update(
            delivery="invalidated",
            complete_ok=True,
            next_action="SHA deixou de ser ancestral da base",
        )
        _apply_counts(out)
        return out

    if facts.get("draft_after_accept") or (
        facts.get("is_draft") and facts.get("delivery_before") == "awaiting_integration"
    ):
        out.update(
            delivery="invalidated",
            complete_ok=True,
            next_action="draft depois do aceite invalida awaiting_integration",
        )
        _apply_counts(out)
        return out

    out["complete_ok"] = True
    pr_state = facts.get("pr_state")
    ci_ok = bool(facts.get("ci_success_on_accepted_sha"))
    review_ok = bool(facts.get("independent_review_on_accepted_sha"))
    not_draft = not bool(facts.get("is_draft"))
    human_sha = bool(facts.get("human_sha_authorization"))
    parents_done = facts.get("parents_done", True)
    guards_on = not facts.get("guards_off")
    updater_on = not facts.get("updater_off")
    ancestor = bool(facts.get("sha_is_ancestor_of_base"))
    merged = pr_state == "MERGED" or bool(facts.get("merged"))
    bytes_ok = bool(facts.get("installed_bytes_match"))
    health_ok = bool(facts.get("health_ok"))

    out["auto_merge_allowed"] = bool(
        ci_ok
        and review_ok
        and not_draft
        and human_sha
        and parents_done
        and guards_on
        and updater_on
        and accepted
        and head == accepted
        and not merged
        and pr_state == "OPEN"
    )

    if applicability == "requires_install" and merged and ancestor and bytes_ok and health_ok:
        out.update(delivery="verified", next_action="entregue de verdade")
    elif applicability == "requires_install" and merged and ancestor and bytes_ok and not health_ok:
        out.update(delivery="installed", next_action="QA verifica no alvo")
    elif merged and ancestor and not_draft and accepted and head == accepted and review_ok:
        out.update(delivery="integrated", next_action="não instalar neste tick")
    elif pr_state == "OPEN" and not_draft and ci_ok and accepted and head == accepted:
        out.update(
            delivery="awaiting_integration",
            next_action="não contar como Integrado; auto-merge só se autorizado",
        )
    elif review_ok and accepted:
        out.update(delivery="reviewed", next_action="abrir PR não-draft ou encerrar se local")
    else:
        out.update(delivery="reviewed", complete_ok=True, next_action="gates de entrega incompletos")

    _apply_counts(out)
    return out


def _apply_counts(out: dict) -> None:
    d = out["delivery"]
    out["counts_as_integrated"] = d in {"integrated", "installed", "verified"}
    out["counts_as_delivered"] = d == "verified"
    if out["recorded_refusal"] and d == "integrated" and out["next_action"].startswith("recusa: merge"):
        out["counts_as_integrated"] = True
        out["counts_as_delivered"] = False


def infer_applicability(contract: str | None, metadata: dict | None) -> str:
    meta = metadata if isinstance(metadata, dict) else {}
    named = meta.get("applicability")
    if named in {"local_phase", "requires_main", "requires_install", "superseded", "unknown"}:
        return named
    if not contract or contract == "local-only":
        phase = meta.get("local_phase")
        if phase in LOCAL_PHASES:
            return "local_phase"
        return "unknown"
    return "requires_main"


def facts_from_receipt(
    receipt: dict,
    *,
    applicability: str,
    contract: str | None,
    accepted_sha: str | None,
    local_phase: str | None = None,
    extra: dict | None = None,
) -> dict:
    classification = receipt.get("classification")
    head = receipt.get("head_sha")
    facts = {
        "applicability": applicability,
        "completion_contract": contract,
        "local_phase": local_phase,
        "pr_state": receipt.get("pr_state"),
        "is_draft": bool(receipt.get("is_draft")),
        "head_sha": head,
        "accepted_sha": accepted_sha,
        "sha_is_ancestor_of_base": bool(receipt.get("sha_is_ancestor_of_base")),
        "merged": receipt.get("pr_state") == "MERGED" or bool(receipt.get("merged")),
        "ci_success_on_accepted_sha": classification == "success" and (
            not accepted_sha or head == accepted_sha
        ),
        "github_error": classification == "infra",
        "delivery_before": extra.get("delivery_before") if extra else None,
    }
    if extra:
        for key, value in extra.items():
            if key not in facts or facts[key] in (None, False, ""):
                facts[key] = value
            elif key not in {
                "applicability", "completion_contract", "pr_state", "head_sha",
                "ci_success_on_accepted_sha", "github_error", "merged",
                "sha_is_ancestor_of_base", "is_draft",
            }:
                facts[key] = value
    return facts


def attach_verdict(receipt: dict, classified: dict) -> dict:
    receipt = dict(receipt)
    receipt["delivery"] = classified["delivery"]
    receipt["counts_as_integrated"] = classified["counts_as_integrated"]
    receipt["counts_as_delivered"] = classified["counts_as_delivered"]
    receipt["auto_merge_allowed"] = classified["auto_merge_allowed"]
    receipt["recorded_refusal"] = classified["recorded_refusal"]
    receipt["error_visible"] = classified["error_visible"]
    receipt["next_action"] = classified["next_action"]
    return receipt
