"""Git facts for the scripts library — read-only, never a write, never a guess.

Every function here answers one question about a file that already exists on
disk, by shelling out to ``git`` with an explicit timeout and
``stdin=DEVNULL``. Nothing is inferred: a repository with no remote reports
"no remote" rather than "unpublished", and a file git has never heard of
reports ``untracked`` rather than an invented version.

The distinction the operator actually asked for — *prepared* vs *reviewed* vs
*published* vs *installed* — is measured, not decorated:

``untracked``/``modified``
    The file on disk differs from (or is absent from) the index. Whatever is
    on GitHub does not describe it.
``committed``
    Clean working copy with a commit, but that commit is not reachable from
    the tracking remote. Local history only.
``published``
    The commit is an ancestor of the remote tracking ref, so it really is on
    the remote.
``review``
    Publication is not review. The only offline evidence of review is a merge
    commit on the ancestry path from the file's commit to the remote ref whose
    subject names a pull request; when there is none we say ``unknown`` and
    give the reason instead of assuming.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Mirrors ``git log --format`` field order in _file_commit().
_LOG_FORMAT = "%H%x1f%h%x1f%cI%x1f%an%x1f%s"

_MERGE_PR_RE = re.compile(r"Merge pull request #(\d+)\b")

# github.com remotes only; anything else yields no web link rather than a URL
# guessed from an unknown forge's path layout.
_GITHUB_SSH_RE = re.compile(r"^git@github\.com:(?P<slug>[^/]+/[^/]+?)(?:\.git)?$")
_GITHUB_HTTPS_RE = re.compile(r"^https://(?:[^@/]+@)?github\.com/(?P<slug>[^/]+/[^/]+?)(?:\.git)?$")


@dataclass(frozen=True)
class GitCommit:
    sha: str
    short_sha: str
    date: str
    author: str
    subject: str


@dataclass(frozen=True)
class GitFacts:
    """Everything git can prove about one file. ``available`` False means the
    question could not be asked (no repo, no git binary, timeout) — the caller
    must render that as unknown, never as 'not committed'."""

    available: bool = False
    reason: str = ""
    repo_root: str = ""
    relpath: str = ""
    state: str = "unknown"  # untracked | modified | committed | published | unknown
    commit: Optional[GitCommit] = None
    remote_url: str = ""
    remote_ref: str = ""
    web_url: str = ""
    history: List[GitCommit] = field(default_factory=list)
    review_state: str = "unknown"  # merged_pr | unknown
    review_reason: str = ""
    review_pr: str = ""
    review_merge_commit: str = ""


def _git(repo: Path, *args: str, timeout: float) -> Optional[str]:
    """Run ``git -C repo <args>``; None on any failure (missing binary, non-zero
    exit, timeout). Callers translate None into an explicit unknown."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def repo_root_for(path: Path, *, timeout: float = 10.0) -> Optional[Path]:
    """The work tree containing *path*, or None when it is not in a repository."""
    start = path if path.is_dir() else path.parent
    out = _git(start, "rev-parse", "--show-toplevel", timeout=timeout)
    if not out or not out.strip():
        return None
    return Path(out.strip())


def bulk_states(repo: Path, relpaths: List[str], *, timeout: float = 10.0) -> Dict[str, str]:
    """Coarse per-file state for a whole root in two git calls instead of 2N.

    Returns ``relpath -> "untracked" | "modified" | "committed"``. A file git
    cannot answer for is simply absent from the mapping, so the caller reports
    unknown rather than inheriting a neighbour's state.
    """
    if not relpaths:
        return {}

    tracked_out = _git(repo, "ls-files", "-z", "--", *relpaths, timeout=timeout)
    if tracked_out is None:
        return {}
    tracked = {p for p in tracked_out.split("\0") if p}

    states: Dict[str, str] = {rel: ("committed" if rel in tracked else "untracked") for rel in relpaths}

    # --porcelain=v1 -z: "XY path\0" records; a rename adds a second NUL-separated
    # path we must consume so the stream stays aligned.
    status_out = _git(repo, "status", "--porcelain=v1", "-z", "--", *relpaths, timeout=timeout)
    if status_out is None:
        return states

    fields = status_out.split("\0")
    index = 0
    while index < len(fields):
        record = fields[index]
        index += 1
        if len(record) < 4:
            continue
        code, path = record[:2], record[3:]
        if code[0] in "RC":
            index += 1  # skip the rename/copy source path
        if path in states:
            states[path] = "untracked" if code == "??" else "modified"
    return states


def _file_commit(repo: Path, relpath: str, timeout: float) -> Optional[GitCommit]:
    out = _git(repo, "log", "-1", f"--format={_LOG_FORMAT}", "--", relpath, timeout=timeout)
    if not out or not out.strip():
        return None
    return _parse_commit(out.strip().splitlines()[0])


def _parse_commit(line: str) -> Optional[GitCommit]:
    parts = line.split("\x1f")
    if len(parts) != 5:
        return None
    return GitCommit(sha=parts[0], short_sha=parts[1], date=parts[2], author=parts[3], subject=parts[4])


def _history(repo: Path, relpath: str, limit: int, timeout: float) -> List[GitCommit]:
    out = _git(repo, "log", f"-{limit}", f"--format={_LOG_FORMAT}", "--", relpath, timeout=timeout)
    if not out:
        return []
    commits = [_parse_commit(line) for line in out.splitlines() if line.strip()]
    return [c for c in commits if c is not None]


def _tracking_ref(repo: Path, timeout: float) -> str:
    """The remote ref to measure publication against: the branch's own upstream
    first, then the remote's default HEAD. Empty when neither exists."""
    for args in (
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"),
        ("symbolic-ref", "--short", "refs/remotes/origin/HEAD"),
    ):
        out = _git(repo, *args, timeout=timeout)
        if out and out.strip():
            return out.strip()
    return ""


def _remote_url(repo: Path, remote_ref: str, timeout: float) -> str:
    remote = remote_ref.split("/", 1)[0] if remote_ref else "origin"
    out = _git(repo, "remote", "get-url", remote, timeout=timeout)
    return out.strip() if out and out.strip() else ""


def github_blob_url(remote_url: str, sha: str, relpath: str) -> str:
    """An https GitHub blob URL, or "" for any remote we cannot map with
    certainty. A wrong link is worse than no link."""
    if not remote_url or not sha or not relpath:
        return ""
    remote_url = remote_url.strip()
    match = _GITHUB_SSH_RE.match(remote_url) or _GITHUB_HTTPS_RE.match(remote_url)
    if not match:
        return ""
    slug = match.group("slug")
    if slug.count("/") != 1 or any(part in ("", ".", "..") for part in slug.split("/")):
        return ""
    # relpath comes from a scan of the work tree, so it is already repo-relative
    # and normalised; refuse anything that could still escape.
    if relpath.startswith("/") or ".." in Path(relpath).parts:
        return ""
    return f"https://github.com/{slug}/blob/{sha}/{relpath}"


def _review_evidence(repo: Path, sha: str, remote_ref: str, timeout: float) -> tuple:
    """(state, reason, pr, merge_commit) for the commit that carries *sha* onto
    the remote ref. Publication alone never counts as review."""
    if not remote_ref:
        return "unknown", "no remote tracking ref to measure a merge against", "", ""
    out = _git(
        repo, "log", "--merges", "--ancestry-path", "--reverse",
        f"--format={_LOG_FORMAT}", f"{sha}..{remote_ref}", timeout=timeout,
    )
    if out is None:
        return "unknown", "git could not walk the ancestry path to the remote ref", "", ""
    for line in out.splitlines():
        commit = _parse_commit(line)
        if commit is None:
            continue
        pr_match = _MERGE_PR_RE.search(commit.subject)
        if pr_match:
            return "merged_pr", "", f"#{pr_match.group(1)}", commit.sha
    return "unknown", "no pull-request merge commit on the path to the remote; publication is not review", "", ""


def facts_for(
    path: Path,
    *,
    coarse_state: Optional[str] = None,
    history_limit: int = 10,
    timeout: float = 10.0,
) -> GitFacts:
    """Full git picture for one file. *coarse_state* is the cheap verdict from
    :func:`bulk_states`; it is only refined here, never contradicted."""
    repo = repo_root_for(path, timeout=timeout)
    if repo is None:
        return GitFacts(available=False, reason="file is not inside a git repository", state="untracked")

    try:
        relpath = path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return GitFacts(available=False, reason="file resolves outside its own repository", repo_root=str(repo))

    state = coarse_state or bulk_states(repo, [relpath], timeout=timeout).get(relpath, "unknown")
    commit = _file_commit(repo, relpath, timeout) if state != "untracked" else None
    remote_ref = _tracking_ref(repo, timeout)
    remote_url = _remote_url(repo, remote_ref, timeout)

    review_state, review_reason, review_pr, review_merge = "unknown", "", "", ""
    if commit and state == "committed":
        if remote_ref and _git(repo, "merge-base", "--is-ancestor", commit.sha, remote_ref, timeout=timeout) is not None:
            state = "published"
        # _review_evidence is the SINGLE place a review verdict is decided,
        # including the no-remote case. Answering "unknown" here as well would
        # duplicate the rule in two places and leave this one untested — which
        # is exactly how a review sensor rots into always-unknown.
        review_state, review_reason, review_pr, review_merge = _review_evidence(
            repo, commit.sha, remote_ref, timeout
        )
    elif commit:
        review_reason = "working copy differs from the commit; review of that commit does not describe this file"

    return GitFacts(
        available=True,
        repo_root=str(repo),
        relpath=relpath,
        state=state,
        commit=commit,
        remote_url=remote_url,
        remote_ref=remote_ref,
        web_url=github_blob_url(remote_url, commit.sha, relpath) if commit else "",
        history=_history(repo, relpath, history_limit, timeout) if commit else [],
        review_state=review_state,
        review_reason=review_reason,
        review_pr=review_pr,
        review_merge_commit=review_merge,
    )
