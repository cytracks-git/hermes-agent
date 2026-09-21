"""A provider wall before any work must not feed the kanban goal loop.

The Ralph judge fail-opens on an empty response (``continue``). A kanban
goal_mode worker that hit a pre-execution quota/auth wall used to treat that
as ``not done yet`` and burn the whole turn budget (12 empty inits, zero
quality judgments of real work, then a sticky ``exhausted N/N turns`` block).

The native contract already maps ``failure_reason`` onto exit 75 (requeue,
no failure) / 78 (park). The loop must honour that classification instead of
collapsing it to ``empty response (nothing to evaluate)``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import cli
from hermes_cli import goals
from hermes_cli.kanban_db import KANBAN_RATE_LIMIT_EXIT_CODE, KANBAN_TERMINAL_PROVIDER_EXIT_CODE


@pytest.fixture(autouse=True)
def _no_inherited_kanban_env(monkeypatch):
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_GOAL_MODE", raising=False)


def _loop(monkeypatch, *, first_response="", first_failure_reason=None, max_turns=12, status="running"):
    """Drive ``run_kanban_goal_loop`` with scripted callbacks. Returns (result, turns, blocks, judges)."""
    turns, blocks, judges = [], [], []

    def _fake_judge(goal, response, **_kw):
        judges.append(response)
        return "continue", "empty response (nothing to evaluate)", False, None, False

    monkeypatch.setattr(goals, "judge_goal", _fake_judge)
    kwargs = dict(
        task_id="t_preflight",
        goal_text="do the thing",
        run_turn=lambda p: turns.append(p) or "",
        task_status_fn=lambda: status,
        block_fn=lambda r: blocks.append(r),
        max_turns=max_turns,
        first_response=first_response,
    )
    if first_failure_reason is not None:
        kwargs["first_failure_reason"] = first_failure_reason
    return goals.run_kanban_goal_loop(**kwargs), turns, blocks, judges


def test_quota_preflight_does_not_burn_the_goal_budget_or_call_the_judge(monkeypatch):
    """Classified rate_limit + empty first turn: stop now, no judge, no extra inits."""
    res, turns, blocks, judges = _loop(
        monkeypatch, first_response="", first_failure_reason="rate_limit", max_turns=12,
    )
    assert judges == [], "zero quality judgments on work that never ran"
    assert turns == [], "must not re-init the agent 12 times"
    assert blocks == [], "dispatcher owns requeue via exit 75; do not sticky-block as budget"
    assert res["outcome"] != "completed_by_worker"
    assert res["outcome"] != "blocked_budget"
    assert res["turns_used"] < 12
    assert "rate_limit" in str(res.get("reason") or "")


def test_auth_preflight_does_not_complete_or_exhaust_budget(monkeypatch):
    res, turns, blocks, judges = _loop(
        monkeypatch, first_response="", first_failure_reason="auth", max_turns=12,
    )
    assert judges == [] and turns == [] and blocks == []
    assert res["outcome"] != "completed_by_worker"
    assert res["outcome"] != "blocked_budget"
    assert "auth" in str(res.get("reason") or "")


def test_legitimate_empty_response_still_continues_the_loop(monkeypatch):
    """Empty output after a real turn (no provider wall) must not false-stop."""
    res, turns, blocks, judges = _loop(
        monkeypatch, first_response="", first_failure_reason=None, max_turns=2,
    )
    assert judges, "legitimate empty still goes to the judge (fail-open continue)"
    assert turns, "the agent is poked once more — this is remaining work, not a wall"
    assert res["outcome"] == "blocked_budget"


def test_eligible_worker_keeps_the_turn_budget_and_can_finish(monkeypatch):
    """Positive: a worker that did real work still loops and can complete."""
    monkeypatch.setattr(
        goals, "judge_goal",
        lambda goal, response, **_kw: ("continue", "not yet", False, None, False),
    )
    turns = []
    finished = {"done": False}

    def _status():
        return "done" if finished["done"] else "running"

    def _run_turn(prompt):
        turns.append(prompt)
        finished["done"] = True
        return "wrote artifact"

    res = goals.run_kanban_goal_loop(
        task_id="t_ok",
        goal_text="ship it",
        run_turn=_run_turn,
        task_status_fn=_status,
        block_fn=lambda r: pytest.fail(f"should not block: {r}"),
        max_turns=12,
        first_response="started the work",
    )
    assert res["outcome"] == "completed_by_worker"
    assert turns == [
        goals.KANBAN_GOAL_CONTINUATION_TEMPLATE.format(reason="not yet"),
    ]
    assert res["turns_used"] == 2


def _stub_kanban_db(monkeypatch):
    """Let ``_run_kanban_goal_loop_q`` reach ``run_kanban_goal_loop`` without a real board."""

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("hermes_cli.kanban_db_connect.connect_closing", lambda: _Conn())
    monkeypatch.setattr(
        "hermes_cli.kanban_db.get_task",
        lambda conn, tid: SimpleNamespace(
            id=tid, status="running", title="t", body="b", goal_mode=True, goal_max_turns=12,
        ),
    )
    monkeypatch.setattr("hermes_cli.kanban_db.goal_run_status", lambda conn, tid, run_id: "running")
    monkeypatch.setattr("hermes_cli.kanban_db.block_task", lambda *a, **k: None)


def _run_q_path(monkeypatch, turn_result):
    """Drive ``_run_single_query_mode`` (the dispatcher ``-q`` worker)."""
    _stub_kanban_db(monkeypatch)
    monkeypatch.setattr(cli, "_should_seed_interactive", lambda *a, **k: False)
    monkeypatch.setattr(cli, "_collect_query_images", lambda q, i: (q, []))
    monkeypatch.setattr(cli, "_collect_kanban_task_images", lambda imgs: [])
    monkeypatch.setattr(cli, "_finalize_single_query", lambda c: None)
    stub = SimpleNamespace(
        _single_query_mode=False,
        _claim_active_session=lambda *a, **k: True,
        console=SimpleNamespace(print=lambda *a, **k: None),
        _show_security_advisories=lambda: None,
        chat=lambda *a, **k: turn_result.get("final_response") if isinstance(turn_result, dict) else None,
        _print_exit_summary=lambda **k: None,
        _last_turn_result=turn_result,
    )
    try:
        cli._run_single_query_mode(stub, "work kanban task t_abc", None, False, True)
    except SystemExit as exc:
        return exc.code
    return None


def test_goal_mode_skips_the_loop_and_exits_75_on_quota_wall(monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_abc")
    monkeypatch.setenv("HERMES_KANBAN_GOAL_MODE", "1")
    called = []
    monkeypatch.setattr(goals, "run_kanban_goal_loop", lambda **k: called.append(k) or {"outcome": "should-not-run"})
    code = _run_q_path(
        monkeypatch,
        {"failed": True, "failure_reason": "rate_limit", "final_response": ""},
    )
    assert called == [], "classified quota wall must not enter the Ralph loop"
    assert code == KANBAN_RATE_LIMIT_EXIT_CODE


def test_goal_mode_skips_the_loop_and_exits_78_on_terminal_auth(monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_abc")
    monkeypatch.setenv("HERMES_KANBAN_GOAL_MODE", "1")
    called = []
    monkeypatch.setattr(goals, "run_kanban_goal_loop", lambda **k: called.append(k) or {})
    code = _run_q_path(
        monkeypatch,
        {"failed": True, "failure_reason": "auth", "final_response": ""},
    )
    assert called == []
    assert code == KANBAN_TERMINAL_PROVIDER_EXIT_CODE


def test_goal_mode_still_runs_the_loop_when_the_first_turn_worked(monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_abc")
    monkeypatch.setenv("HERMES_KANBAN_GOAL_MODE", "1")
    called = []
    monkeypatch.setattr(goals, "run_kanban_goal_loop", lambda **k: called.append(k) or {"outcome": "ok"})
    code = _run_q_path(
        monkeypatch,
        {"final_response": "wrote the file", "completed": True},
    )
    assert len(called) == 1
    assert called[0]["first_response"] == "wrote the file"
    assert code == 0


def test_quiet_goal_mode_skips_the_loop_on_quota_wall(monkeypatch):
    """``-Q`` path: same skip, same native exit 75."""
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_abc")
    monkeypatch.setenv("HERMES_KANBAN_GOAL_MODE", "1")
    called = []
    monkeypatch.setattr(goals, "run_kanban_goal_loop", lambda **k: called.append(k) or {})
    _stub_kanban_db(monkeypatch)
    agent = SimpleNamespace(
        run_conversation=lambda **k: {"failed": True, "failure_reason": "rate_limit", "final_response": ""},
        session_id="s-1",
    )
    try:
        cli._run_quiet_single_query(
            SimpleNamespace(agent=agent, conversation_history=[], session_id="s-1"),
            "do the thing",
        )
    except SystemExit as exc:
        code = exc.code
    else:
        code = None
    assert called == []
    assert code == KANBAN_RATE_LIMIT_EXIT_CODE


def test_anthropic_model_cooldown_auth_error_is_rate_limit_not_empty_response(monkeypatch):
    """The live incident: token exists, this model is benched → AuthError must classify as rate_limit."""
    from hermes_cli.auth import AuthError, is_rate_limited_auth_error
    from hermes_cli.runtime_provider import _anthropic_token_or_raise

    monkeypatch.setattr(
        "agent.anthropic_credentials.resolve_anthropic_token",
        lambda model=None: None if model else "sk-ant-present",
    )
    with pytest.raises(AuthError) as exc_info:
        _anthropic_token_or_raise(model="claude-opus-5")
    err = exc_info.value
    assert "rate-limited" in str(err).lower()
    assert "claude-opus-5" in str(err)
    assert is_rate_limited_auth_error(err) is True
    # The kanban worker exit mapper keys on failure_reason, not the log string.
    result = {
        "failed": True,
        "failure_reason": err.code if err.code == "rate_limit" else None,
        "final_response": "",
        "error": str(err),
    }
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_abc")
    assert err.code == "rate_limit"
    assert cli._single_query_exit_code(result) == KANBAN_RATE_LIMIT_EXIT_CODE
    assert cli._kanban_goal_loop_allowed(result) is False


def test_credential_init_autherror_stamps_rate_limit_and_exits_75(monkeypatch):
    """The live path: resolve_runtime_provider raises before any turn dict exists."""
    from hermes_cli.auth import AuthError

    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_abc")
    monkeypatch.setenv("HERMES_KANBAN_GOAL_MODE", "1")
    err = AuthError(
        "Anthropic credentials are rate-limited for claude-opus-5; other Claude models remain available",
        code="rate_limit",
        retryable=True,
    )
    obj = SimpleNamespace(_last_runtime_error=err, _last_turn_result=None)
    cli._stamp_preflight_turn_result(obj)
    assert obj._last_turn_result["failure_reason"] == "rate_limit"
    assert obj._last_turn_result["failed"] is True
    assert cli._kanban_goal_loop_allowed(obj._last_turn_result) is False
    assert cli._single_query_exit_code(obj._last_turn_result) == KANBAN_RATE_LIMIT_EXIT_CODE
