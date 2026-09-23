"""Scripts library core — catalogue scan, doc extraction and lifecycle.

Each test states the behaviour contract it protects. The negative controls are
the point of the file: a sensor that only ever sees well-formed input proves
nothing about the cases that actually threaten the surface (a symlink planted
inside a root, a file with no docstring, a repo with no remote).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from hermes_cli import scripts_library as sl
from hermes_cli import scripts_library_vcs as vcs


def _write(path: Path, content: str, *, mode: int = 0o644) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)
    return path


@pytest.fixture
def home(tmp_path: Path) -> Path:
    scripts = tmp_path / "hermes" / "scripts"
    scripts.mkdir(parents=True)
    return tmp_path / "hermes"


# --- Scanning ---------------------------------------------------------------


def test_scan_finds_scripts_and_reports_the_roots_it_looked_at(home: Path):
    _write(home / "scripts" / "backup.sh", "#!/bin/bash\n# Back up the state DB.\n")

    result = sl.scan(hermes_home=home)

    assert [entry.name for entry in result.entries] == ["backup.sh"]
    # Roots travel with the result: the UI must be able to say WHERE it looked,
    # not just what it found.
    assert [root.origin for root in result.roots] == ["hermes_home"]
    assert result.roots[0].exists is True


def test_missing_root_is_reported_not_swallowed(tmp_path: Path):
    """'No scripts found' and 'the directory is gone' are different facts."""
    result = sl.scan(hermes_home=tmp_path / "nonexistent-home")

    assert result.entries == []
    assert result.roots[0].exists is False
    assert result.roots[0].error


def test_non_script_files_are_not_catalogued(home: Path):
    """NEGATIVE CONTROL: the closed extension list is what keeps credential
    files and data out of the catalogue by construction."""
    _write(home / "scripts" / "real.py", "'''Doc.'''\n")
    _write(home / "scripts" / ".env", "SECRET_TOKEN=hunter2\n")
    _write(home / "scripts" / "credentials.json", '{"api_key": "hunter2"}')
    _write(home / "scripts" / "notes.txt", "not a script")

    names = {entry.name for entry in sl.scan(hermes_home=home).entries}

    assert names == {"real.py"}


def test_symlinked_directory_inside_a_root_is_not_followed(home: Path, tmp_path: Path):
    """NEGATIVE CONTROL — traversal. A symlink planted in a scanned root must
    not pull the scan into an unrelated tree."""
    outside = tmp_path / "outside"
    _write(outside / "stolen.py", "'''Should never be catalogued.'''\n")
    os.symlink(outside, home / "scripts" / "link")

    names = {entry.name for entry in sl.scan(hermes_home=home).entries}

    assert "stolen.py" not in names


def test_binary_file_with_a_script_extension_yields_no_documentation(home: Path):
    """NEGATIVE CONTROL: a NUL-bearing file must not be decoded into the UI."""
    path = home / "scripts" / "compiled.py"
    path.write_bytes(b"\x7fELF\x00\x00\x00binary garbage")

    entries = sl.scan(hermes_home=home).entries

    assert [entry.name for entry in entries] == ["compiled.py"]
    assert entries[0].purpose == ""


def test_the_same_file_reached_through_two_roots_is_one_entry(home: Path, tmp_path: Path):
    """Identity is the resolved path, so overlapping roots dedupe."""
    _write(home / "scripts" / "shared.py", "'''Shared.'''\n")
    config = {"scripts_library": {"roots": [{"path": str(home / "scripts"), "label": "Again"}]}}

    result = sl.scan(hermes_home=home, config=config)

    assert len(result.entries) == 1


def test_entry_ids_are_stable_across_scans(home: Path):
    _write(home / "scripts" / "stable.py", "'''Stable.'''\n")

    first = sl.scan(hermes_home=home).entries[0].id
    second = sl.scan(hermes_home=home).entries[0].id

    assert first == second


def test_configured_root_expands_user_and_env_vars(home: Path, tmp_path: Path, monkeypatch):
    extra = tmp_path / "team-scripts"
    _write(extra / "deploy.sh", "#!/bin/sh\n# Deploy.\n")
    monkeypatch.setenv("TEAM_SCRIPTS", str(extra))

    result = sl.scan(hermes_home=home, config={"scripts_library": {"roots": ["${TEAM_SCRIPTS}"]}})

    assert [entry.name for entry in result.entries] == ["deploy.sh"]


def test_malformed_configured_root_is_skipped_without_killing_the_scan(home: Path):
    _write(home / "scripts" / "ok.py", "'''Fine.'''\n")
    config = {"scripts_library": {"roots": [{"label": "no path"}, 42, ""]}}

    result = sl.scan(hermes_home=home, config=config)

    assert [entry.name for entry in result.entries] == ["ok.py"]


# --- Documentation extraction ----------------------------------------------


def test_python_docstring_is_read_without_importing_the_module(home: Path, tmp_path: Path):
    """The load-bearing safety property: parsing, not importing.

    The script writes a sentinel file at import time. If the catalogue ever
    switched to importing modules to read ``__doc__``, this file would exist.
    """
    sentinel = tmp_path / "IMPORTED"
    _write(
        home / "scripts" / "dangerous.py",
        f'"""Collect disk usage."""\n\nfrom pathlib import Path\nPath({str(sentinel)!r}).write_text("executed")\n',
    )

    entries = sl.scan(hermes_home=home).entries

    assert entries[0].purpose == "Collect disk usage."
    assert not sentinel.exists(), "catalogued code was executed — the scan must only parse"


def test_python_file_that_does_not_parse_still_gets_its_comment_header(home: Path):
    _write(home / "scripts" / "broken.py", "#!/usr/bin/env python3\n# Legacy collector.\ndef (:\n")

    entries = sl.scan(hermes_home=home).entries

    assert entries[0].purpose == "Legacy collector."


def test_shell_header_comment_becomes_the_purpose_and_shebang_the_interpreter(home: Path):
    _write(home / "scripts" / "rotate.sh", "#!/usr/bin/env bash\n# Rotate gateway logs.\n# Keeps two backups.\n\nls\n")

    entry = sl.scan(hermes_home=home).entries[0]

    assert entry.purpose == "Rotate gateway logs."
    assert entry.interpreter == "bash"


def test_script_without_documentation_reports_an_empty_purpose(home: Path):
    """NEGATIVE CONTROL: absent documentation must read as absent, never be
    filled in from the filename."""
    _write(home / "scripts" / "mystery.sh", "#!/bin/sh\nls -la\n")

    assert sl.scan(hermes_home=home).entries[0].purpose == ""


def test_sections_are_parsed_only_when_the_author_wrote_them(home: Path):
    doc = (
        "Collect metrics.\n\n"
        "Usage:\n  metrics.py --since 7d\n\n"
        "Exit codes:\n  0 ok\n  2 unreachable\n"
    )
    _write(home / "scripts" / "metrics.py", f'"""{doc}"""\n')
    entry = sl.scan(hermes_home=home).entries[0]

    sections = sl.parse_sections(sl.extract_doc(Path(entry.path), "python")[1])

    assert "metrics.py --since 7d" in sections["usage"]
    assert "2 unreachable" in sections["exit_codes"]
    assert "dependencies" not in sections


def test_run_command_uses_the_interpreter_for_a_non_executable_script(home: Path):
    _write(home / "scripts" / "plain.py", "'''Doc.'''\n", mode=0o644)
    entry = sl.scan(hermes_home=home).entries[0]

    assert sl.run_command_for(entry).startswith("python3 ")


def test_run_command_is_the_path_alone_for_an_executable_with_a_shebang(home: Path):
    _write(home / "scripts" / "exec.sh", "#!/usr/bin/env bash\n# Doc.\n", mode=0o755)
    entry = sl.scan(hermes_home=home).entries[0]

    assert sl.run_command_for(entry) == entry.path


# --- Git facts and lifecycle ------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, stdin=subprocess.DEVNULL)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / "scripts").mkdir(parents=True)
    _git(path.parent, "init", "-q", "repo")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    return path


def test_untracked_file_is_reported_as_untracked_never_as_a_version(repo: Path):
    """The operator's explicit ask: a local script with no commit must say so."""
    _write(repo / "scripts" / "new.py", "'''New.'''\n")

    facts = vcs.facts_for(repo / "scripts" / "new.py")

    assert facts.state == "untracked"
    assert facts.commit is None


def test_committed_file_reports_its_commit(repo: Path):
    _write(repo / "scripts" / "tool.py", "'''Tool.'''\n")
    _git(repo, "add", "scripts/tool.py")
    _git(repo, "commit", "-qm", "add tool")

    facts = vcs.facts_for(repo / "scripts" / "tool.py")

    assert facts.state == "committed"
    assert facts.commit is not None
    assert facts.commit.subject == "add tool"


def test_edited_file_is_modified_so_the_commit_does_not_describe_it(repo: Path):
    """NEGATIVE CONTROL: a file on GitHub does not prove the local bytes."""
    path = _write(repo / "scripts" / "tool.py", "'''Tool.'''\n")
    _git(repo, "add", "scripts/tool.py")
    _git(repo, "commit", "-qm", "add tool")
    path.write_text("'''Tool, edited locally.'''\n", encoding="utf-8")

    facts = vcs.facts_for(path)

    assert facts.state == "modified"


def test_no_remote_means_unknown_review_with_a_stated_reason(repo: Path):
    """A repo with no remote must not be reported as unreviewed OR reviewed."""
    _write(repo / "scripts" / "tool.py", "'''Tool.'''\n")
    _git(repo, "add", "scripts/tool.py")
    _git(repo, "commit", "-qm", "add tool")

    facts = vcs.facts_for(repo / "scripts" / "tool.py")

    assert facts.review_state == "unknown"
    assert facts.review_reason


def test_file_outside_any_repository_reports_unavailable_not_untracked_by_guess(tmp_path: Path):
    path = _write(tmp_path / "loose" / "thing.py", "'''Loose.'''\n")

    facts = vcs.facts_for(path)

    assert facts.available is False
    assert facts.reason


def test_lifecycle_never_claims_a_stage_it_did_not_measure(repo: Path):
    """The card asked to distinguish prepared/reviewed/published/installed.

    ``installed`` is deliberately absent — nothing here measures installation —
    and ``reviewed`` reports unknown with a reason rather than inferring review
    from publication.
    """
    _write(repo / "scripts" / "tool.py", "'''Tool.'''\n")
    _git(repo, "add", "scripts/tool.py")
    _git(repo, "commit", "-qm", "add tool")
    entry = sl.scan(hermes_home=repo, config={"scripts_library": {"roots": [str(repo / "scripts")]}}).entries[0]

    lifecycle = sl.detail_for(entry)["lifecycle"]
    stages = {stage["stage"]: stage for stage in lifecycle["stages"]}

    assert set(stages) == {"prepared", "committed", "reviewed", "published"}
    assert stages["prepared"]["status"] == "yes"
    assert stages["reviewed"]["status"] == "unknown"
    assert stages["reviewed"]["evidence"]
    # Every stage carries its evidence — a status with no evidence is an opinion.
    assert all(stage["evidence"] for stage in lifecycle["stages"])


def test_publication_is_measured_against_the_remote_not_assumed(repo: Path, tmp_path: Path):
    """POSITIVE CONTROL for the published state, and its negative twin."""
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(remote)], check=True, capture_output=True, stdin=subprocess.DEVNULL
    )
    _write(repo / "scripts" / "tool.py", "'''Tool.'''\n")
    _git(repo, "add", "scripts/tool.py")
    _git(repo, "commit", "-qm", "add tool")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "HEAD:refs/heads/main")

    published = vcs.facts_for(repo / "scripts" / "tool.py")
    assert published.state == "published"

    # NEGATIVE: a further local commit is committed, not published.
    _write(repo / "scripts" / "tool.py", "'''Tool v2.'''\n")
    _git(repo, "add", "scripts/tool.py")
    _git(repo, "commit", "-qm", "edit tool")

    assert vcs.facts_for(repo / "scripts" / "tool.py").state == "committed"


def test_merge_commit_naming_a_pull_request_is_the_only_review_evidence(repo: Path, tmp_path: Path):
    """POSITIVE CONTROL for review: a real PR merge on the path to the remote.

    Paired with ``test_no_remote_means_unknown_review_with_a_stated_reason``
    (negative), this proves the sensor discriminates instead of always
    answering the same thing.
    """
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "-q", "--bare", str(remote)], check=True, capture_output=True, stdin=subprocess.DEVNULL
    )
    _write(repo / "README.md", "base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "-M", "main")

    _git(repo, "checkout", "-q", "-b", "feature")
    _write(repo / "scripts" / "tool.py", "'''Tool.'''\n")
    _git(repo, "add", "scripts/tool.py")
    _git(repo, "commit", "-qm", "add tool")

    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "Merge pull request #42 from fork/feature", "feature")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "main")

    facts = vcs.facts_for(repo / "scripts" / "tool.py")

    assert facts.review_state == "merged_pr"
    assert facts.review_pr == "#42"


def test_github_url_is_built_only_for_a_github_remote(tmp_path: Path):
    """NEGATIVE CONTROL: a wrong link is worse than no link."""
    sha = "a" * 40

    assert vcs.github_blob_url("git@github.com:owner/repo.git", sha, "scripts/x.py") == (
        f"https://github.com/owner/repo/blob/{sha}/scripts/x.py"
    )
    assert vcs.github_blob_url("https://gitlab.com/owner/repo.git", sha, "scripts/x.py") == ""
    assert vcs.github_blob_url("/srv/git/local.git", sha, "scripts/x.py") == ""
    # A relative path that escapes the repo never becomes a link.
    assert vcs.github_blob_url("git@github.com:owner/repo.git", sha, "../../etc/passwd") == ""
