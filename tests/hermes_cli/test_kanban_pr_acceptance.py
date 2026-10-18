"""Two lifecycle invariants, using real SQLite and a local GitHub HTTP contract."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect


@pytest.fixture
def github(tmp_path, monkeypatch):
    state = {"conclusion": "success", "head": "a" * 40, "reads": 0, "requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state["requests"].append(self.path)
            sha = state["head"]
            if self.path == "/graphql":
                value = {"data": {"repository": {"pullRequest": {
                    "headRefOid": sha, "baseRefName": "main",
                    "state": state.get("pr_state", "OPEN"),
                    "isDraft": bool(state.get("is_draft")),
                    "mergeCommit": {"oid": sha} if state.get("pr_state") == "MERGED" else None,
                    "baseRef": {"branchProtectionRule": {"requiredStatusChecks": (
                        [] if state.get("no_required") else
                        [{"context": "required", "app": {"databaseId": 1}}]
                    )}}}}}}
            elif "/rules/branches/" in self.path:
                value = [[]]
            elif "/check-runs" in self.path:
                run = {"id": 42, "name": "required", "head_sha": sha,
                       "app": {"id": 1}, "status": "in_progress" if state["conclusion"] == "pending" else "completed", "conclusion": state["conclusion"],
                       "html_url": "https://github.com/acme/repo/actions/runs/42"}
                if state.get("stale"):
                    run["head_sha"] = "b" * 40
                runs = [] if state.get("missing") else [run]
                value = [{"total_count": 100 + len(runs), "check_runs": [
                    {**run, "id": 1000 + i, "name": "optional", "conclusion": "skipped"}
                    for i in range(100)]}, {"total_count": 100 + len(runs), "check_runs": runs}]
                if state.get("race"):
                    state["race"]()
                if state.get("head_change"):
                    state["head"] = "b" * 40
            elif "/statuses" in self.path:
                value = [[]]
            elif "/compare/" in self.path:
                value = {"status": state.get("compare_status", "ahead")}
            elif "/pulls/" in self.path:
                value = {"head": {"sha": sha}, "base": {"ref": "main"}, "state": "open"}
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    shim = tmp_path / "bin"
    shim.mkdir()
    gh = shim / "gh"
    gh.write_text(f"#!{sys.executable}\nimport sys,urllib.request\n"
                  f"u='http://127.0.0.1:{server.server_port}/'+sys.argv[2]\n"
                  "print(urllib.request.urlopen(u).read().decode())\n")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", str(shim) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    kb.init_db()
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.linux_only
def test_pr_completion_requires_current_required_evidence(github):
    with connect() as conn:
        for conclusion in ("failure", "pending", "cancelled", "timed_out", "action_required", "neutral", "skipped", None, "success"):
            github.update(conclusion=conclusion, head="a" * 40)
            tid = kb.create_task(conn, title="Publish", completion_contract="acme/repo")
            ok = kb.complete_task(conn, tid, metadata={"published_pr": "https://github.com/acme/repo/pull/7"})
            assert ok is (conclusion == "success")
            task = kb.get_task(conn, tid)
            assert task is not None
            assert (task.status == "done") is ok
            receipts = [json.loads(r[0]) for r in conn.execute(
                "SELECT payload FROM task_events WHERE task_id=? AND kind='pr_acceptance'", (tid,))]
            assert receipts and receipts[-1]["head_sha"] == "a" * 40
            assert receipts[-1]["ok"] is ok
            if conclusion == "success":
                assert task.delivery_status != "integrated"
                assert task.delivery_status != "verified"
                payload = json.loads(conn.execute(
                    "SELECT payload FROM task_events WHERE task_id=? AND kind='delivery' "
                    "ORDER BY id DESC LIMIT 1", (tid,)).fetchone()[0])
                assert payload["counts_as_integrated"] is False
                assert payload["delivery"] == "reviewed"
            if not ok:
                assert task.status in {"running", "ready", "blocked", "review"}
                assert "retry" in receipts[-1]["recovery"]
                assert receipts[-1]["checks"][0]["id"] == 42
        for fault in ("missing", "stale", "head_change"):
            github.update(conclusion="success", head="a" * 40)
            github[fault] = True
            tid = kb.create_task(conn, title=fault, completion_contract="acme/repo")
            assert not kb.complete_task(conn, tid, metadata={"published_pr": "https://github.com/acme/repo/pull/7"})
            assert kb.get_task(conn, tid).status != "done"
            github.pop(fault)
        # Omission and a sibling repository cannot downgrade the stored declaration.
        tid = kb.create_task(conn, title="publish", completion_contract="acme/repo")
        assert not kb.complete_task(conn, tid, summary="local green")
        assert not kb.complete_task(conn, tid, metadata={"published_pr": "https://github.com/other/repo/pull/7"})
        before = len(github["requests"])
        local = kb.create_task(conn, title="local", completion_contract="local-only")
        assert kb.complete_task(conn, local, summary="https://github.com/acme/repo/pull/7 is background context",
                                metadata={"local_phase": "desenho"})
        assert len(github["requests"]) == before
        local_task = kb.get_task(conn, local)
        assert local_task is not None
        assert local_task.status == "done"
        assert local_task.delivery_status == "n/a"


@pytest.mark.linux_only
def test_open_ci_with_accepted_sha_is_awaiting_integration_not_integrated(github):
    sha = "a" * 40
    github.update(conclusion="success", head=sha)
    with connect() as conn:
        tid = kb.create_task(conn, title="exige-main", completion_contract="acme/repo")
        assert kb.complete_task(conn, tid, metadata={
            "published_pr": "https://github.com/acme/repo/pull/7",
            "accepted_sha": sha,
            "applicability": "requires_main",
            "independent_review_on_accepted_sha": True,
        })
        task = kb.get_task(conn, tid)
        assert task is not None
        assert task.status == "done"
        assert task.delivery_status == "awaiting_integration"
        assert task.accepted_sha == sha
        payload = json.loads(conn.execute(
            "SELECT payload FROM task_events WHERE task_id=? AND kind='delivery' "
            "ORDER BY id DESC LIMIT 1", (tid,)).fetchone()[0])
        assert payload["counts_as_integrated"] is False
        assert payload["counts_as_delivered"] is False


@pytest.mark.linux_only
def test_merged_ancestral_reviewed_sha_is_integrated(github):
    sha = "a" * 40
    github.update(conclusion="success", head=sha, pr_state="MERGED", compare_status="ahead")
    with connect() as conn:
        tid = kb.create_task(conn, title="merged", completion_contract="acme/repo")
        assert kb.complete_task(conn, tid, metadata={
            "published_pr": "https://github.com/acme/repo/pull/7",
            "accepted_sha": sha,
            "applicability": "requires_main",
            "independent_review_on_accepted_sha": True,
        })
        task = kb.get_task(conn, tid)
        assert task is not None
        assert task.status == "done"
        assert task.delivery_status == "integrated"
        payload = json.loads(conn.execute(
            "SELECT payload FROM task_events WHERE task_id=? AND kind='delivery' "
            "ORDER BY id DESC LIMIT 1", (tid,)).fetchone()[0])
        assert payload["counts_as_integrated"] is True


@pytest.mark.linux_only
def test_dispatcher_invalidates_stale_head_without_rewriting_done(github):
    sha = "a" * 40
    github.update(conclusion="success", head=sha)
    with connect() as conn:
        tid = kb.create_task(conn, title="stale-head", completion_contract="acme/repo")
        assert kb.complete_task(conn, tid, metadata={
            "published_pr": "https://github.com/acme/repo/pull/7",
            "accepted_sha": sha,
            "applicability": "requires_main",
        })
        assert kb.get_task(conn, tid) is not None
        assert kb.get_task(conn, tid).delivery_status == "awaiting_integration"
        github["head"] = "b" * 40
        from hermes_cli.kanban_delivery_store import reconcile_delivery
        invalidated = reconcile_delivery(conn)
        task = kb.get_task(conn, tid)
        assert task is not None
        assert tid in invalidated
        assert task.status == "done"
        assert task.delivery_status == "invalidated"


@pytest.mark.linux_only
def test_draft_open_ci_is_not_awaiting_integration(github):
    sha = "a" * 40
    github.update(conclusion="success", head=sha, is_draft=True)
    with connect() as conn:
        tid = kb.create_task(conn, title="draft", completion_contract="acme/repo")
        assert kb.complete_task(conn, tid, metadata={
            "published_pr": "https://github.com/acme/repo/pull/7",
            "accepted_sha": sha,
            "applicability": "requires_main",
        })
        task = kb.get_task(conn, tid)
        assert task is not None
        assert task.status == "done"
        assert task.delivery_status == "reviewed"
        assert task.delivery_status != "awaiting_integration"
        assert task.delivery_status != "integrated"


@pytest.mark.linux_only
def test_acceptance_receipts_and_terminal_write_share_run_ownership(github):
    with connect() as conn:
        for conclusion in ("success", "failure"):
            tid = kb.create_task(conn, title="race", completion_contract="acme/repo")
            owner = kb.claim_task(conn, tid)
            run_id = owner.current_run_id
            def reclaim():
                with connect() as rival:
                    assert kb.block_task(rival, tid, reason="Reassigned during acceptance")
                    assert kb.unblock_task(rival, tid)
                    github["replacement"] = kb.claim_task(rival, tid).current_run_id
            github.update(conclusion=conclusion, race=reclaim)
            assert not kb.complete_task(conn, tid, expected_run_id=run_id,
                metadata={"published_pr": "https://github.com/acme/repo/pull/7"})
            assert kb.get_task(conn, tid).current_run_id == github["replacement"]
            assert github["replacement"] != run_id
            assert kb.get_task(conn, tid).status != "done"
            assert conn.execute("SELECT count(*) FROM task_events WHERE task_id=? AND kind='pr_acceptance'", (tid,)).fetchone()[0] == 0
            github.pop("race")


def test_merged_without_required_checks_measures_ancestry_open_still_missing(github):
    """Fork with required=[] must not refuse MERGED+ancestral; OPEN still missing."""
    from hermes_cli.kanban_pr_acceptance import collect_acceptance

    sha = "a" * 40
    github.update(conclusion="success", head=sha, no_required=True, pr_state="OPEN")
    open_receipt = collect_acceptance("https://github.com/acme/repo/pull/7", None)
    assert open_receipt["ok"] is False
    assert open_receipt["sha_is_ancestor_of_base"] is False

    github.update(pr_state="MERGED", compare_status="ahead")
    merged = collect_acceptance("https://github.com/acme/repo/pull/7", None)
    assert merged["ok"] is True
    assert merged["classification"] == "success"
    assert merged["sha_is_ancestor_of_base"] is True
