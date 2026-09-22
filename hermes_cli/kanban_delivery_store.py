"""Persist and reconcile delivery_status without touching execution columns."""
from __future__ import annotations

from hermes_cli.kanban_db_connect import write_txn
from hermes_cli.kanban_delivery import (
    attach_verdict,
    facts_from_receipt,
    infer_applicability,
    verdict,
)
from hermes_cli.kanban_pr_acceptance import _PR, collect_acceptance

_WATCH = ("reviewed", "awaiting_integration", "integrated")


def extra_facts_from_metadata(metadata, *, independent_review: bool = False) -> dict:
    meta = metadata if isinstance(metadata, dict) else {}
    extra = {
        "independent_review_on_accepted_sha": bool(
            meta.get("independent_review_on_accepted_sha") or independent_review
        ),
        "human_sha_authorization": bool(meta.get("human_sha_authorization")),
        "require_main": bool(meta.get("require_main")),
        "admin_bypass": bool(meta.get("admin_bypass")),
        "force_push": bool(meta.get("force_push")),
        "guards_off": bool(meta.get("guards_off")),
        "updater_off": bool(meta.get("updater_off")),
        "synthetic_h1": bool(meta.get("synthetic_h1")),
        "mass_draft": bool(meta.get("mass_draft")),
        "claim_verified_from_merge_only": bool(meta.get("claim_verified_from_merge_only")),
        "summary_as_proof": bool(meta.get("summary_as_proof")),
        "executor_summary_as_review": bool(meta.get("executor_summary_as_review")),
        "second_dispatcher": bool(meta.get("second_dispatcher")),
        "retry_after_crash": bool(meta.get("retry_after_crash")),
        "prior_action_applied": bool(meta.get("prior_action_applied")),
        "merge_reverted": bool(meta.get("merge_reverted")),
        "draft_after_accept": bool(meta.get("draft_after_accept")),
        "parents_done": meta.get("parents_done", True),
        "installed_bytes_match": bool(meta.get("installed_bytes_match")),
        "health_ok": bool(meta.get("health_ok")),
    }
    if meta.get("delivery_before"):
        extra["delivery_before"] = meta["delivery_before"]
    return extra


def _independent_review(conn, task_id) -> bool:
    row = conn.execute(
        "SELECT 1 FROM task_runs WHERE task_id=? AND lower(profile)='revisor' "
        "AND outcome='completed' LIMIT 1",
        (task_id,),
    ).fetchone()
    return bool(row)


def classify_task(conn, task_id, receipt: dict | None, metadata) -> dict:
    row = conn.execute(
        "SELECT completion_contract, delivery_status, applicability, accepted_sha, local_phase "
        "FROM tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    meta = metadata if isinstance(metadata, dict) else {}
    contract = (row["completion_contract"] if row else None) or meta.get("completion_contract")
    applicability = infer_applicability(contract, meta)
    if row and row["applicability"] and "applicability" not in meta:
        applicability = row["applicability"]
    accepted_sha = meta.get("accepted_sha") or (row["accepted_sha"] if row else None)
    local_phase = meta.get("local_phase") or (row["local_phase"] if row else None)
    extra = extra_facts_from_metadata(meta, independent_review=_independent_review(conn, task_id))
    if row and row["delivery_status"]:
        extra.setdefault("delivery_before", row["delivery_status"])
    if receipt is None:
        facts = {
            "applicability": applicability,
            "completion_contract": contract if contract != "local-only" else "local-only",
            "local_phase": local_phase,
            "accepted_sha": accepted_sha,
        }
        facts.update(extra)
        classified = verdict(facts)
        empty = {
            "ok": True,
            "classification": "local",
            "head_sha": None,
            "pr_url": None,
            "checks": [],
            "pr_state": None,
            "is_draft": False,
            "sha_is_ancestor_of_base": False,
        }
        return attach_verdict(empty, classified)
    facts = facts_from_receipt(
        receipt,
        applicability=applicability,
        contract=contract,
        accepted_sha=accepted_sha,
        local_phase=local_phase,
        extra=extra,
    )
    return attach_verdict(receipt, verdict(facts))


def persist_delivery(conn, task_id, classified: dict, metadata) -> None:
    from hermes_cli.kanban_db import _append_event

    meta = metadata if isinstance(metadata, dict) else {}
    applicability = classified.get("applicability") or infer_applicability(
        classified.get("completion_contract") or meta.get("completion_contract"), meta
    )
    accepted_sha = meta.get("accepted_sha") or classified.get("accepted_sha")
    local_phase = meta.get("local_phase")
    conn.execute(
        "UPDATE tasks SET delivery_status=?, applicability=?, "
        "accepted_sha=COALESCE(?, accepted_sha), local_phase=COALESCE(?, local_phase) "
        "WHERE id=?",
        (classified["delivery"], applicability, accepted_sha, local_phase, task_id),
    )
    _append_event(conn, task_id, "delivery", {
        "delivery": classified["delivery"],
        "counts_as_integrated": classified.get("counts_as_integrated"),
        "counts_as_delivered": classified.get("counts_as_delivered"),
        "next_action": classified.get("next_action"),
        "recorded_refusal": classified.get("recorded_refusal"),
        "error_visible": classified.get("error_visible"),
        "head_sha": classified.get("head_sha"),
        "accepted_sha": accepted_sha,
    })


def apply_delivery_on_complete(conn, task_id, acceptance, metadata) -> dict:
    receipt = None if acceptance is None else acceptance[1]
    classified = classify_task(conn, task_id, receipt, metadata)
    persist_delivery(conn, task_id, classified, metadata)
    return classified


def reconcile_delivery(conn, *, dry_run: bool = False) -> list[str]:
    """Reread PR heads; invalidate delivery without touching execution status."""
    if dry_run:
        return []
    try:
        rows = conn.execute(
            "SELECT id, completion_contract, accepted_sha, delivery_status, applicability, local_phase "
            "FROM tasks WHERE delivery_status IN (?, ?, ?) AND completion_contract LIKE 'https://github.com/%/pull/%'",
            _WATCH,
        ).fetchall()
    except Exception:
        return []
    changed: list[str] = []
    for row in rows:
        contract = row["completion_contract"]
        if not _PR.fullmatch(contract or ""):
            continue
        receipt = collect_acceptance(contract, contract, accepted_sha=row["accepted_sha"])
        extra = extra_facts_from_metadata({
            "delivery_before": row["delivery_status"],
            "accepted_sha": row["accepted_sha"],
            "applicability": row["applicability"],
            "local_phase": row["local_phase"],
        }, independent_review=_independent_review(conn, row["id"]))
        extra["delivery_before"] = row["delivery_status"]
        if receipt.get("classification") == "infra":
            continue
        if row["delivery_status"] == "integrated" and not receipt.get("sha_is_ancestor_of_base"):
            extra["merge_reverted"] = True
        if receipt.get("is_draft") and row["delivery_status"] == "awaiting_integration":
            extra["draft_after_accept"] = True
        facts = facts_from_receipt(
            receipt,
            applicability=row["applicability"] or "requires_main",
            contract=contract,
            accepted_sha=row["accepted_sha"],
            local_phase=row["local_phase"],
            extra=extra,
        )
        classified = attach_verdict(receipt, verdict(facts))
        if classified["delivery"] == row["delivery_status"]:
            continue
        with write_txn(conn):
            persist_delivery(conn, row["id"], classified, {
                "accepted_sha": row["accepted_sha"],
                "applicability": row["applicability"],
                "local_phase": row["local_phase"],
            })
        if classified["delivery"] == "invalidated":
            changed.append(row["id"])
    return changed
