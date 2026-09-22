"""Runner routing for the upstream org vs a User-owned public fork.

The production decision lives in ``scripts/ci/runner_labels.py`` and is
inlined into workflow YAML as the expression that module prints. These
tests call that function (not a copy) and scan the committed workflows.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "ci" / "runner_labels.py"
_spec = importlib.util.spec_from_file_location("runner_labels", _PATH)
if _spec is None or _spec.loader is None:
    raise ImportError("Failed to load runner_labels.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

UPSTREAM = _mod.UPSTREAM_REPOSITORY
FORK = "cytracks-git/hermes-agent"
WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"

resolve_runner = _mod.resolve_runner
resolve_timeout_minutes = _mod.resolve_timeout_minutes
github_runs_on_expression = _mod.github_runs_on_expression
github_timeout_expression = _mod.github_timeout_expression
ungated_larger_runner_hits = _mod.ungated_larger_runner_hits
scan_workflows = _mod.scan_workflows
gated_timeout_hits = _mod.gated_timeout_hits
RUNNERS = _mod.RUNNERS
TIMEOUTS = _mod.TIMEOUTS
WORKFLOW_RUNNER_KINDS = _mod.WORKFLOW_RUNNER_KINDS
WORKFLOW_TIMEOUT_KINDS = _mod.WORKFLOW_TIMEOUT_KINDS
LARGER_LABELS = _mod.LARGER_LABELS


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("linux-96", "ubuntu-latest-96-core"),
        ("linux-32", "ubuntu-latest-32-core"),
        ("linux-32-arm", "ubuntu-latest-32-arm-core"),
        ("windows-32", "windows-latest-32-core"),
    ],
)
def test_upstream_keeps_larger_labels(kind: str, expected: str) -> None:
    assert resolve_runner(UPSTREAM, kind) == expected


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("linux-96", "ubuntu-latest"),
        ("linux-32", "ubuntu-latest"),
        ("linux-32-arm", "ubuntu-24.04-arm"),
        ("windows-32", "windows-latest"),
    ],
)
def test_fork_uses_standard_public_labels(kind: str, expected: str) -> None:
    assert resolve_runner(FORK, kind) == expected
    assert expected not in LARGER_LABELS


def test_fork_never_resolves_a_larger_label() -> None:
    for kind in RUNNERS:
        label = resolve_runner(FORK, kind)
        assert label not in LARGER_LABELS, (kind, label)


def test_another_org_fork_also_gets_standard_runners() -> None:
    assert resolve_runner("acme/hermes-agent", "linux-96") == "ubuntu-latest"


def test_unknown_kind_and_malformed_repo_fail_closed() -> None:
    with pytest.raises(ValueError, match="unknown runner kind"):
        resolve_runner(UPSTREAM, "gpu-secret")
    with pytest.raises(ValueError, match="owner/name"):
        resolve_runner("nous", "linux-96")
    with pytest.raises(ValueError, match="owner/name"):
        resolve_runner("", "linux-96")


def test_timeout_grows_on_fork_and_holds_on_upstream() -> None:
    assert resolve_timeout_minutes(UPSTREAM, "linux-96") == 30
    assert resolve_timeout_minutes(FORK, "linux-96") == 120
    assert resolve_timeout_minutes(UPSTREAM, "windows-32") == 30
    assert resolve_timeout_minutes(FORK, "windows-32") == 30
    for kind, (upstream, fork) in TIMEOUTS.items():
        assert resolve_timeout_minutes(UPSTREAM, kind) == upstream
        assert resolve_timeout_minutes(FORK, kind) == fork
        assert fork >= upstream


def test_ungated_bare_label_is_a_hit() -> None:
    text = "jobs:\n  test:\n    runs-on: ubuntu-latest-96-core\n"
    hits = ungated_larger_runner_hits(text)
    assert hits == [(3, "    runs-on: ubuntu-latest-96-core")]


def test_gated_expression_is_not_a_hit() -> None:
    expr = github_runs_on_expression("linux-96")
    text = f"jobs:\n  test:\n    runs-on: {expr}\n"
    assert ungated_larger_runner_hits(text) == []


def test_wrong_standard_fallback_is_a_hit() -> None:
    text = (
        "    runs-on: ${{ github.repository == 'NousResearch/hermes-agent'"
        " && 'ubuntu-latest-96-core' || 'ubuntu-latest-96-core' }}\n"
    )
    hits = ungated_larger_runner_hits(text)
    assert hits and "ubuntu-latest-96-core" in hits[0][1]


def test_owner_predicate_is_not_the_gate() -> None:
    text = (
        "    runs-on: ${{ github.repository_owner == 'NousResearch'"
        " && 'ubuntu-latest-96-core' || 'ubuntu-latest' }}\n"
    )
    hits = ungated_larger_runner_hits(text)
    assert hits, "owner-only predicate must not pass for a repo that is not the upstream"


def test_matrix_pointer_is_not_a_hit_matrix_entry_is() -> None:
    text = (
        "    runs-on: ${{ matrix.runner }}\n"
        "    strategy:\n"
        "      matrix:\n"
        "        include:\n"
        "          - runner: windows-latest-32-core\n"
    )
    hits = ungated_larger_runner_hits(text)
    assert len(hits) == 1
    assert hits[0][0] == 5


def test_comment_mention_is_not_a_hit() -> None:
    text = "    # One 96-core runner for the whole suite.\n    runs-on: ubuntu-latest\n"
    assert ungated_larger_runner_hits(text) == []


def test_standard_runs_on_is_not_a_hit() -> None:
    assert ungated_larger_runner_hits("    runs-on: ubuntu-latest\n") == []
    assert ungated_larger_runner_hits("    runs-on: windows-latest\n") == []
    assert ungated_larger_runner_hits("    runs-on: macos-latest\n") == []


def test_committed_workflows_have_no_ungated_larger_runners() -> None:
    hits = scan_workflows(WORKFLOWS)
    assert hits == [], "ungated larger runners:\n" + "\n".join(
        f"{path}:{lineno}: {raw.strip()}" for path, lineno, raw in hits
    )


def test_committed_workflows_inline_the_canonical_expressions() -> None:
    missing: list[str] = []
    for filename, kinds in WORKFLOW_RUNNER_KINDS.items():
        text = (WORKFLOWS / filename).read_text(encoding="utf-8")
        for kind in kinds:
            expr = github_runs_on_expression(kind)
            if expr not in text:
                missing.append(f"{filename} missing runs-on {kind}: {expr}")
            count = text.count(expr)
            assert count >= 1
    for filename, kinds in WORKFLOW_TIMEOUT_KINDS.items():
        text = (WORKFLOWS / filename).read_text(encoding="utf-8")
        for kind in kinds:
            expr = github_timeout_expression(kind)
            if expr not in text:
                missing.append(f"{filename} missing timeout {kind}: {expr}")
    assert missing == [], "\n".join(missing)


def test_scanner_floor_sees_every_declared_workflow() -> None:
    """If the kind table empties out, the suite would pass over nothing."""
    assert len(WORKFLOW_RUNNER_KINDS) >= 7
    files = list(WORKFLOWS.glob("*.yml")) + list(WORKFLOWS.glob("*.yaml"))
    assert len(files) >= 20
    for filename in WORKFLOW_RUNNER_KINDS:
        assert (WORKFLOWS / filename).is_file(), filename


def test_scan_empty_dir_is_not_clean() -> None:
    with pytest.raises(FileNotFoundError):
        scan_workflows(Path("/tmp/hermes-runner-labels-no-such-dir-3c9f"))
