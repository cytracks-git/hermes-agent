#!/usr/bin/env python3
"""Map CI jobs onto runners that exist on this GitHub repository.

Nous Research names larger GitHub-hosted runners (96-core / 32-core /
32-arm-core). Those labels are not standard public-repo images: they exist
only where an org admin created them. A User-owned public fork has none, so
a job with ``runs-on: ubuntu-latest-96-core`` queues forever (PR #5 / #6 on
cytracks-git/hermes-agent, 2026-09-22).

This module is the single mapping. Workflow YAML inlines the GitHub
expression that ``github_runs_on_expression`` prints; the scanner below
refuses a larger label that is not that expression. Tests cover both the
function and the committed workflows.

Identity is ``github.repository == NousResearch/hermes-agent``, the same
predicate docker.yml / deploy-site.yml already use. Owner-only would send
a hypothetical NousResearch/<other-repo> onto runners it may not have.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

UPSTREAM_REPOSITORY = "NousResearch/hermes-agent"

# kind -> (upstream larger label, fork standard label).
# Standard public labels: https://docs.github.com/en/actions/reference/runners/github-hosted-runners
RUNNERS: dict[str, tuple[str, str]] = {
    "linux-96": ("ubuntu-latest-96-core", "ubuntu-latest"),
    "linux-32": ("ubuntu-latest-32-core", "ubuntu-latest"),
    "linux-32-arm": ("ubuntu-latest-32-arm-core", "ubuntu-24.04-arm"),
    "windows-32": ("windows-latest-32-core", "windows-latest"),
}

# Job wall-clock minutes: (upstream, fork). Fork has ~4 cores vs 32/96, same
# suite. python-96: 126s measured at 96 workers (run 32549672063) → ~50 min
# at 4 workers + setup; 120 is the buffer. Equal pairs stay a scalar in YAML.
TIMEOUTS: dict[str, tuple[int, int]] = {
    "linux-96": (30, 120),
    "linux-32": (30, 90),
    "linux-32-nix": (60, 180),
    "linux-32-e2e": (20, 60),
    "windows-32": (30, 30),
}

# Which kinds each workflow must inline. docker.yml is included so a later
# relaxation of its NousResearch-only `if:` cannot resurrect the queue; the
# `if:` itself is not this module's job.
WORKFLOW_RUNNER_KINDS: dict[str, tuple[str, ...]] = {
    "tests.yml": ("linux-96",),
    "tests-os.yml": ("windows-32",),
    "nix.yml": ("linux-32",),
    "js-tests.yml": ("linux-32",),
    "rust-tests.yml": ("linux-32",),
    "e2e-desktop.yml": ("linux-32",),
    "docker.yml": ("linux-32", "linux-32-arm"),
}

WORKFLOW_TIMEOUT_KINDS: dict[str, tuple[str, ...]] = {
    "tests.yml": ("linux-96",),
    "nix.yml": ("linux-32-nix",),
    "js-tests.yml": ("linux-32",),
    "rust-tests.yml": ("linux-32",),
    "e2e-desktop.yml": ("linux-32-e2e",),
}

_LARGER_TO_STANDARD = {larger: standard for larger, standard in RUNNERS.values()}
LARGER_LABELS = frozenset(_LARGER_TO_STANDARD)

_RUNNER_KEY = re.compile(
    r"^(?P<indent>\s*)(?:-\s+)?(?P<key>runs-on|runner):\s*(?P<value>.+?)\s*$"
)
_GATED_RUNNER = re.compile(
    r"^\$\{\{\s*github\.repository\s*==\s*'"
    + re.escape(UPSTREAM_REPOSITORY)
    + r"'\s*&&\s*'(?P<larger>[^']+)'\s*\|\|\s*'(?P<standard>[^']+)'\s*\}\}$"
)
_GATED_TIMEOUT = re.compile(
    r"^\$\{\{\s*github\.repository\s*==\s*'"
    + re.escape(UPSTREAM_REPOSITORY)
    + r"'\s*&&\s*(?P<upstream>\d+)\s*\|\|\s*(?P<fork>\d+)\s*\}\}$"
)


def resolve_runner(repository: str, kind: str) -> str:
    """Return the ``runs-on`` label for *repository* and runner *kind*."""
    if not repository or "/" not in repository:
        raise ValueError(f"repository must be owner/name, got {repository!r}")
    try:
        larger, standard = RUNNERS[kind]
    except KeyError as exc:
        raise ValueError(f"unknown runner kind {kind!r}") from exc
    if repository == UPSTREAM_REPOSITORY:
        return larger
    return standard


def resolve_timeout_minutes(repository: str, kind: str) -> int:
    """Return job ``timeout-minutes`` for *repository* and timeout *kind*."""
    if not repository or "/" not in repository:
        raise ValueError(f"repository must be owner/name, got {repository!r}")
    try:
        upstream, fork = TIMEOUTS[kind]
    except KeyError as exc:
        raise ValueError(f"unknown timeout kind {kind!r}") from exc
    if fork < upstream:
        raise ValueError(f"{kind}: fork timeout {fork} < upstream {upstream}")
    if repository == UPSTREAM_REPOSITORY:
        return upstream
    return fork


def github_runs_on_expression(kind: str) -> str:
    """GitHub expression a workflow inlines as ``runs-on`` / matrix ``runner``."""
    larger, standard = RUNNERS[kind]
    return (
        "${{ github.repository == '"
        f"{UPSTREAM_REPOSITORY}' && '{larger}' || '{standard}' }}}}"
    )


def github_timeout_expression(kind: str) -> str:
    """GitHub expression a workflow inlines as ``timeout-minutes``."""
    upstream, fork = TIMEOUTS[kind]
    return (
        "${{ github.repository == '"
        f"{UPSTREAM_REPOSITORY}' && {upstream} || {fork} }}}}"
    )


def _strip_yaml_comment(value: str) -> str:
    in_single = False
    in_double = False
    for i, ch in enumerate(value):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return value[:i].rstrip()
    return value.rstrip()


def ungated_larger_runner_hits(text: str) -> list[tuple[int, str]]:
    """Lines whose ``runs-on`` / ``runner`` value is a larger label without the gate.

    ``runs-on: ${{ matrix.runner }}`` is not a hit; the matrix ``runner:``
    entries are scanned on their own lines.
    """
    hits: list[tuple[int, str]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        match = _RUNNER_KEY.match(raw)
        if match is None:
            continue
        value = _strip_yaml_comment(match.group("value"))
        gated = _GATED_RUNNER.match(value)
        if gated is not None:
            larger = gated.group("larger")
            standard = gated.group("standard")
            expected = _LARGER_TO_STANDARD.get(larger)
            if expected is None or standard != expected:
                hits.append((lineno, raw))
            continue
        # Bare label or any other expression that names a larger runner.
        if any(label in value for label in LARGER_LABELS):
            hits.append((lineno, raw))
    return hits


def scan_workflows(workflows_dir: Path) -> list[tuple[Path, int, str]]:
    """Ungated larger-runner hits across ``*.yml`` / ``*.yaml`` in *workflows_dir*."""
    found: list[tuple[Path, int, str]] = []
    files = sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml"))
    if not files:
        raise FileNotFoundError(f"no workflow files in {workflows_dir}")
    for path in files:
        text = path.read_text(encoding="utf-8")
        for lineno, raw in ungated_larger_runner_hits(text):
            found.append((path, lineno, raw))
    return found


def gated_timeout_hits(text: str) -> list[tuple[int, int, int]]:
    """``(lineno, upstream, fork)`` for each gated timeout-minutes expression."""
    hits: list[tuple[int, int, int]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped.startswith("timeout-minutes:"):
            continue
        value = _strip_yaml_comment(stripped.split(":", 1)[1].strip())
        gated = _GATED_TIMEOUT.match(value)
        if gated is None:
            continue
        hits.append((lineno, int(gated.group("upstream")), int(gated.group("fork"))))
    return hits


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[2]
    workflows = repo_root / ".github" / "workflows"
    hits = scan_workflows(workflows)
    if hits:
        for path, lineno, raw in hits:
            print(f"{path}:{lineno}: ungated larger runner: {raw.strip()}", file=sys.stderr)
        print(f"ungated={len(hits)}", file=sys.stderr)
        return 1
    print(f"ok: no ungated larger runners under {workflows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
