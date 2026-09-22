"""Oracle parity: production verdict() matches frozen casos.json (a4edf2f456)."""
import json
from pathlib import Path

from hermes_cli.kanban_delivery import verdict

_CASES = Path(__file__).parent / "fixtures" / "entrega_verificavel_casos.json"


def _cases():
    payload = json.loads(_CASES.read_text())
    assert payload["freeze_desenho"].startswith("a4edf2f456")
    return payload["cases"]


def test_production_verdict_matches_frozen_oracle_for_every_case():
    cases = _cases()
    assert len(cases) >= 27
    ids = [c["id"] for c in cases]
    assert ids.count("N01") == 1 and ids.count("P01") == 1
    for case in cases:
        got = verdict(case["facts"])
        expected = case["expected"]
        for key, value in expected.items():
            if key not in got:
                continue
            assert got[key] == value, f"{case['id']} {key}: {got[key]!r} != {value!r}"


def test_open_ci_is_never_integrated():
    got = verdict({
        "applicability": "requires_main",
        "completion_contract": "acme/repo",
        "pr_state": "OPEN",
        "is_draft": False,
        "ci_success_on_accepted_sha": True,
        "independent_review_on_accepted_sha": True,
        "accepted_sha": "a" * 40,
        "head_sha": "a" * 40,
        "human_sha_authorization": False,
    })
    assert got["delivery"] == "awaiting_integration"
    assert got["complete_ok"] is True
    assert got["counts_as_integrated"] is False
    assert got["counts_as_delivered"] is False


def test_local_phase_does_not_require_main():
    got = verdict({
        "applicability": "local_phase",
        "local_phase": "desenho",
        "completion_contract": "local-only",
    })
    assert got["delivery"] == "n/a"
    assert got["complete_ok"] is True
    assert got["github_calls_expected"] == 0


def test_require_main_on_local_phase_is_recorded_refusal():
    got = verdict({
        "applicability": "local_phase",
        "local_phase": "desenho",
        "completion_contract": "local-only",
        "require_main": True,
    })
    assert got["recorded_refusal"] is True
    assert got["delivery"] == "n/a"
    assert got["counts_as_delivered"] is False
