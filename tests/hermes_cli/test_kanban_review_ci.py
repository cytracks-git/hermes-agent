"""A review handoff that names a published PR spawns a ``[ci]`` child whose
completion is the PR's exact-head CI, so CI waits never sit on (and never
block-loop) the implementation card. Real SQLite + local GitHub HTTP contract.
"""
import json

from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect
from tests.hermes_cli.test_kanban_pr_acceptance import github  # noqa: F401  (fixture)

PR = "https://github.com/acme/repo/pull/7"


def _children(conn, tid):
    return [r[0] for r in conn.execute("SELECT child_id FROM task_links WHERE parent_id=?", (tid,))]


def _review(conn, tid, run_id, **metadata):
    assert kb.request_review(conn, tid, summary="done", metadata=metadata or None,
                             reviewer="revisor", expected_run_id=run_id)


def test_review_with_published_pr_spawns_ci_child_gated_on_latest_exact_head(github):  # noqa: F811
    sha = "a" * 40
    with connect() as conn:
        tid = kb.create_task(conn, title="impl", assignee="executor")
        run = kb.claim_task(conn, tid).current_run_id
        _review(conn, tid, run, published_pr=PR, head_sha=sha)
        (child_id,) = _children(conn, tid)
        child = kb.get_task(conn, child_id)
        assert child.assignee == "revisor" and child.assignee != "executor"
        assert child.completion_contract == PR
        assert child.status == "todo"  # waits for the implementation review
        assert sha[:8] in child.title and child.title.startswith("[ci]")
        payload = json.loads(conn.execute(
            "SELECT payload FROM task_events WHERE task_id=? AND kind='review_requested'",
            (tid,)).fetchone()[0])
        assert payload["ci_child"] == child_id

        # Re-review after changes reuses the same CI card (no fan-out per round).
        review_run = kb.claim_review_task(conn, tid).current_run_id
        assert kb.request_changes(conn, tid, reason="fix", expected_run_id=review_run)[0]
        run = kb.claim_task(conn, tid).current_run_id
        _review(conn, tid, run, published_pr=PR, head_sha="c" * 40)
        assert _children(conn, tid) == [child_id]

        assert kb.complete_task(conn, tid, summary="miolo PASSA")
        assert kb.get_task(conn, child_id).status == "ready"

        # Negative controls: an old-head success and a latest cancelled rerun
        # (over an older success) both refuse the CI card.
        github.update(conclusion="success", head=sha, stale=True)
        assert not kb.complete_task(conn, child_id, metadata={"published_pr": PR})
        github.pop("stale")
        github.update(conclusion="cancelled", extra_runs=[{"id": 41, "conclusion": "success"}])
        assert not kb.complete_task(conn, child_id, metadata={"published_pr": PR})
        assert kb.get_task(conn, child_id).status != "done"
        # Positive control: latest run success over a superseded cancelled one.
        github.update(conclusion="success", extra_runs=[{"id": 41, "conclusion": "cancelled"}])
        assert kb.complete_task(conn, child_id, metadata={"published_pr": PR})
        assert kb.get_task(conn, child_id).status == "done"


def test_review_without_pr_or_routed_to_author_spawns_no_ci_child(github):  # noqa: F811
    with connect() as conn:
        plain = kb.create_task(conn, title="no pr", assignee="executor")
        _review(conn, plain, kb.claim_task(conn, plain).current_run_id, commit="abc")
        assert _children(conn, plain) == []

        bogus = kb.create_task(conn, title="bad url", assignee="executor")
        _review(conn, bogus, kb.claim_task(conn, bogus).current_run_id,
                published_pr="https://github.com/acme/repo/pulls")
        assert _children(conn, bogus) == []

        own = kb.create_task(conn, title="self", assignee="revisor")
        run = kb.claim_task(conn, own).current_run_id
        _review(conn, own, run, published_pr=PR)
        assert _children(conn, own) == []
