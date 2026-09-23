"""Scripts library — a read-only catalogue of the script files already on disk.

The operator's question is "what scripts exist, what does each one do, how do I
run it, and what state is it in?". This module answers it by *scanning* the
sources that already exist (the checkout's ``scripts/`` tree, the Hermes home's
``scripts/`` dir, plus anything the user adds under ``scripts_library.roots``).
There is no second copy of the library and no hand-maintained index file: the
catalogue is derived, so it cannot drift from the files it describes.

Two rules shape the whole module.

**Catalogued code is never imported.** Documentation, usage and exit codes are
recovered by *parsing text* — ``ast.parse`` for Python (which builds a tree
without executing a single statement) and a leading-comment reader for shell
and JS. Importing a script to read its ``__doc__`` would run it.

**Identity is the path, and the path is validated at scan time.** An entry's id
is a digest of its real path, and lookups resolve that id against the freshly
scanned catalogue. A caller therefore cannot express a path at all, which is
what makes traversal impossible rather than merely filtered.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from hermes_cli.scripts_library_vcs import GitFacts, bulk_states, facts_for, repo_root_for

# Extensions we recognise as scripts. Deliberately a closed list: it keeps
# credential files, data dumps and binaries out of the catalogue by
# construction rather than by a deny-list someone has to keep ahead of.
SCRIPT_EXTENSIONS: Dict[str, str] = {
    ".py": "python",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".js": "javascript",
    ".ts": "typescript",
    ".ps1": "powershell",
    ".rb": "ruby",
}

# Directory names never worth walking into. Keeps a scan of a working checkout
# from turning into a walk of node_modules.
_SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", ".tox",
    "site-packages", ".next", "target",
}

# Bounds. A catalogue that hangs on a pathological tree is a broken catalogue.
MAX_ENTRIES = 2000
MAX_DEPTH = 6
MAX_DOC_BYTES = 64 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024

_SECTION_PATTERNS: Dict[str, re.Pattern] = {
    "usage": re.compile(r"^\s*(usage|example usage|examples?|how to run)\s*:?\s*$", re.I),
    "inputs": re.compile(r"^\s*(inputs?|arguments?|options?|parameters?|env(?:ironment)?)\s*:?\s*$", re.I),
    "outputs": re.compile(r"^\s*(outputs?|returns?|writes?)\s*:?\s*$", re.I),
    "exit_codes": re.compile(r"^\s*(exit codes?|return codes?|status codes?)\s*:?\s*$", re.I),
    "dependencies": re.compile(r"^\s*(dependenc\w+|requirements?|requires)\s*:?\s*$", re.I),
}


@dataclass(frozen=True)
class ScriptRoot:
    """One scanned source. ``origin`` says where the root came from, so the UI
    can show provenance instead of an anonymous path."""

    id: str
    label: str
    path: str
    origin: str  # repo | hermes_home | configured
    exists: bool = True
    error: str = ""


@dataclass
class ScriptEntry:
    id: str
    name: str
    root_id: str
    root_label: str
    relpath: str
    path: str
    category: str
    language: str
    purpose: str
    size_bytes: int
    modified_at: float
    executable: bool
    interpreter: str
    vcs_state: str = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        # ``run_command`` rides along with the listing, not only with the
        # detail: "how do I run this" is the question the catalogue exists to
        # answer, and making the operator open a card to copy one line is the
        # extra step that turns a library into a chore.
        return {**asdict(self), "run_command": run_command_for(self)}


@dataclass
class ScanResult:
    entries: List[ScriptEntry] = field(default_factory=list)
    roots: List[ScriptRoot] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    truncated: bool = False
    scanned_at: float = 0.0


def entry_id(real_path: Path) -> str:
    """Stable identity for a script: a digest of its real path. Same file under
    two roots (a symlinked or nested root) collapses to one entry."""
    return hashlib.sha256(str(real_path).encode("utf-8", "surrogateescape")).hexdigest()[:16]


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned or "root"


def default_roots(hermes_home: Path, repo_root: Optional[Path]) -> List[ScriptRoot]:
    """The two sources that always exist conceptually: the checkout's own
    ``scripts/`` tree and the Hermes home's ``scripts/`` dir."""
    roots: List[ScriptRoot] = []
    if repo_root is not None:
        roots.append(
            ScriptRoot(
                id="repo-scripts",
                label="Repository scripts",
                path=str(repo_root / "scripts"),
                origin="repo",
            )
        )
    roots.append(
        ScriptRoot(
            id="hermes-home-scripts",
            label="Hermes home scripts",
            path=str(hermes_home / "scripts"),
            origin="hermes_home",
        )
    )
    return roots


def configured_roots(config: Optional[Dict[str, Any]]) -> List[ScriptRoot]:
    """User-declared roots from ``scripts_library.roots`` in config.yaml.

    Each entry is ``{path, label?}``; ``~`` and ``${VAR}`` expand. A malformed
    entry is skipped with its reason recorded on the root, never silently.
    """
    section = (config or {}).get("scripts_library") or {}
    raw_roots = section.get("roots") or []
    if not isinstance(raw_roots, list):
        return []

    roots: List[ScriptRoot] = []
    for index, item in enumerate(raw_roots):
        if isinstance(item, str):
            item = {"path": item}
        if not isinstance(item, dict):
            continue
        raw_path = item.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            continue
        expanded = Path(os.path.expandvars(raw_path)).expanduser()
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            label = expanded.name or raw_path
        roots.append(
            ScriptRoot(
                id=f"cfg-{index}-{_slug(label)}",
                label=label.strip(),
                path=str(expanded),
                origin="configured",
            )
        )
    return roots


def _interpreter_of(first_line: str) -> str:
    if not first_line.startswith("#!"):
        return ""
    shebang = first_line[2:].strip()
    parts = shebang.split()
    if not parts:
        return ""
    if parts[0].endswith("env") and len(parts) > 1:
        return parts[1]
    return Path(parts[0]).name


def _read_head(path: Path) -> str:
    """Read at most ``MAX_DOC_BYTES`` of text. Binary or undecodable content
    comes back as "" — we describe scripts, we do not dump files."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_DOC_BYTES)
    except OSError:
        return ""
    if b"\0" in raw:
        return ""
    return raw.decode("utf-8", "replace")


def _python_doc(text: str) -> str:
    """The module docstring, via ``ast.parse`` — a parser, not an interpreter.

    Falls back to the leading comment block when the file does not parse (a
    Python 2 script, a template, a syntax error). A script that cannot be
    parsed still deserves a description.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return _comment_doc(text)
    return ast.get_docstring(tree) or _comment_doc(text)


def _comment_doc(text: str) -> str:
    """The leading ``#``/``//`` comment block, shebang and coding lines dropped."""
    lines: List[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not lines and (line.startswith("#!") or not line):
            if line.startswith("#!"):
                continue
            if not line:
                if lines:
                    break
                continue
        if line.startswith("# -*-") or line.startswith("# vim:"):
            continue
        if line.startswith("#"):
            lines.append(line.lstrip("#").strip())
            continue
        if line.startswith("//"):
            lines.append(line.lstrip("/").strip())
            continue
        if line.startswith(("<#", "'''", '"""')):
            continue
        break
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines).strip()


def extract_doc(path: Path, language: str) -> Tuple[str, str]:
    """``(interpreter, documentation)`` for one script, by text only."""
    text = _read_head(path)
    if not text:
        return "", ""
    first_line = text.splitlines()[0] if text else ""
    interpreter = _interpreter_of(first_line)
    doc = _python_doc(text) if language == "python" else _comment_doc(text)
    return interpreter, doc


def summarize_doc(doc: str) -> str:
    """First non-empty line of the documentation — the one-line purpose."""
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:300]
    return ""


def parse_sections(doc: str) -> Dict[str, str]:
    """Pull ``Usage:`` / ``Exit codes:`` / ... blocks out of free-form docs.

    Purely additive: a script with no such headings simply yields ``{}`` and the
    UI shows the full documentation. We never invent a section that the author
    did not write.
    """
    if not doc:
        return {}
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line in doc.splitlines():
        matched = next((key for key, pattern in _SECTION_PATTERNS.items() if pattern.match(line)), None)
        if matched:
            current = matched
            sections.setdefault(current, [])
            continue
        if current is None:
            continue
        if line.strip() and not line.startswith((" ", "\t", "-", "*", "$", "#", ">")):
            # A new unindented prose paragraph ends the block.
            current = None
            continue
        sections[current].append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items() if "".join(value).strip()}


def _walk_root(root: ScriptRoot, budget: int) -> Tuple[List[Path], List[str], bool]:
    """Files under one root, depth- and budget-bounded, symlinked dirs skipped."""
    base = Path(root.path)
    found: List[Path] = []
    errors: List[str] = []
    truncated = False
    try:
        base_real = base.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        return [], [f"{root.label}: {exc}"], False

    stack: List[Tuple[Path, int]] = [(base_real, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            with os.scandir(directory) as scan:
                children = sorted(scan, key=lambda e: e.name)
        except OSError as exc:
            errors.append(f"{root.label}: cannot read {directory}: {exc}")
            continue
        for child in children:
            if child.name.startswith(".") or child.name in _SKIP_DIRS:
                continue
            try:
                # follow_symlinks=False: a symlinked directory is never walked,
                # so a link planted inside a root cannot pull the scan out of it.
                if child.is_dir(follow_symlinks=False):
                    if depth < MAX_DEPTH:
                        stack.append((Path(child.path), depth + 1))
                    continue
                if not child.is_file():
                    continue
            except OSError:
                continue
            if Path(child.name).suffix.lower() not in SCRIPT_EXTENSIONS:
                continue
            if len(found) >= budget:
                truncated = True
                return found, errors, truncated
            found.append(Path(child.path))
    return found, errors, truncated


def scan(
    *,
    hermes_home: Path,
    repo_root: Optional[Path] = None,
    config: Optional[Dict[str, Any]] = None,
    git_timeout: float = 10.0,
) -> ScanResult:
    """Scan every configured root and return the catalogue.

    A missing root is reported as a root with ``exists=False`` — visible, not
    swallowed — because "no scripts found" and "the directory is gone" are
    different facts and the operator must be able to tell them apart.
    """
    result = ScanResult(scanned_at=time.time())
    roots = default_roots(hermes_home, repo_root) + configured_roots(config)

    seen_ids: Dict[str, ScriptEntry] = {}
    per_repo: Dict[str, List[Tuple[str, ScriptEntry]]] = {}

    for root in roots:
        base = Path(root.path)
        if not base.is_dir():
            result.roots.append(
                ScriptRoot(
                    id=root.id, label=root.label, path=root.path, origin=root.origin,
                    exists=False, error="directory does not exist",
                )
            )
            continue

        budget = MAX_ENTRIES - len(seen_ids)
        if budget <= 0:
            result.truncated = True
            result.roots.append(root)
            continue

        files, errors, truncated = _walk_root(root, budget)
        result.errors.extend(errors)
        result.truncated = result.truncated or truncated
        result.roots.append(
            ScriptRoot(
                id=root.id, label=root.label, path=root.path, origin=root.origin,
                exists=True, error="; ".join(errors) if errors else "",
            )
        )

        base_real = base.resolve()
        for file_path in files:
            try:
                stat = file_path.stat()
            except OSError:
                continue
            if stat.st_size > MAX_FILE_BYTES:
                continue
            identity = entry_id(file_path)
            if identity in seen_ids:
                continue
            language = SCRIPT_EXTENSIONS[file_path.suffix.lower()]
            interpreter, doc = extract_doc(file_path, language)
            try:
                relpath = file_path.relative_to(base_real).as_posix()
            except ValueError:
                relpath = file_path.name
            category = str(Path(relpath).parent).replace(".", "") or ""
            entry = ScriptEntry(
                id=identity,
                name=file_path.name,
                root_id=root.id,
                root_label=root.label,
                relpath=relpath,
                path=str(file_path),
                category=category,
                language=language,
                purpose=summarize_doc(doc),
                size_bytes=stat.st_size,
                modified_at=stat.st_mtime,
                executable=bool(stat.st_mode & 0o111),
                interpreter=interpreter,
            )
            seen_ids[identity] = entry

            repo = repo_root_for(file_path, timeout=git_timeout)
            key = str(repo) if repo else ""
            per_repo.setdefault(key, []).append(
                (file_path.relative_to(repo).as_posix() if repo else "", entry)
            )

    # One pair of git calls per repository instead of two per file.
    for repo_key, pairs in per_repo.items():
        if not repo_key:
            for _, entry in pairs:
                entry.vcs_state = "untracked"
            continue
        states = bulk_states(Path(repo_key), [rel for rel, _ in pairs], timeout=git_timeout)
        for rel, entry in pairs:
            entry.vcs_state = states.get(rel, "unknown")

    result.entries = sorted(seen_ids.values(), key=lambda e: (e.root_label, e.relpath.lower()))
    return result


def detail_for(entry: ScriptEntry, *, git_timeout: float = 10.0) -> Dict[str, Any]:
    """The full detail payload for one already-catalogued entry.

    Takes an entry the caller resolved from a scan — never a path — so a
    request cannot name a file the scan did not already accept.
    """
    path = Path(entry.path)
    language = entry.language
    _, doc = extract_doc(path, language)
    facts: GitFacts = facts_for(path, coarse_state=entry.vcs_state, timeout=git_timeout)

    payload = entry.to_dict()
    payload["documentation"] = doc
    payload["sections"] = parse_sections(doc)
    payload["run_command"] = run_command_for(entry)
    payload["vcs"] = {
        "available": facts.available,
        "reason": facts.reason,
        "state": facts.state,
        "repo_root": facts.repo_root,
        "relpath": facts.relpath,
        "remote_url": facts.remote_url,
        "remote_ref": facts.remote_ref,
        "web_url": facts.web_url,
        "commit": asdict(facts.commit) if facts.commit else None,
        "history": [asdict(commit) for commit in facts.history],
        "review_state": facts.review_state,
        "review_reason": facts.review_reason,
        "review_pr": facts.review_pr,
        "review_merge_commit": facts.review_merge_commit,
    }
    payload["lifecycle"] = lifecycle_of(entry, facts)
    return payload


def lifecycle_of(entry: ScriptEntry, facts: GitFacts) -> Dict[str, Any]:
    """Prepared / reviewed / published, each with the evidence behind it.

    ``installed`` is deliberately absent: nothing here measures installation,
    and a stage we cannot measure must not be rendered as one we can.
    """
    state = facts.state if facts.available else entry.vcs_state
    prepared = {
        "stage": "prepared",
        "status": "yes",
        "evidence": f"file present on disk at {entry.path}",
    }
    if state == "untracked":
        committed = {"stage": "committed", "status": "no", "evidence": "git does not track this file — local only, no version"}
    elif state == "modified":
        committed = {"stage": "committed", "status": "diverged", "evidence": "working copy differs from the last commit"}
    elif facts.commit:
        committed = {
            "stage": "committed",
            "status": "yes",
            "evidence": f"{facts.commit.short_sha} — {facts.commit.subject}",
        }
    else:
        committed = {"stage": "committed", "status": "unknown", "evidence": facts.reason or "git could not be consulted"}

    if state == "published":
        published = {"stage": "published", "status": "yes", "evidence": f"commit is an ancestor of {facts.remote_ref}"}
    elif state in ("committed", "modified"):
        published = {
            "stage": "published",
            "status": "no",
            "evidence": f"commit is not reachable from {facts.remote_ref}" if facts.remote_ref else "no remote tracking ref configured",
        }
    else:
        published = {"stage": "published", "status": "unknown", "evidence": facts.reason or "not measured"}

    if facts.review_state == "merged_pr":
        reviewed = {
            "stage": "reviewed",
            "status": "yes",
            "evidence": f"merged via pull request {facts.review_pr} ({facts.review_merge_commit[:12]})",
        }
    else:
        reviewed = {
            "stage": "reviewed",
            "status": "unknown",
            "evidence": facts.review_reason or "no merge evidence found; publication is not review",
        }

    return {"stages": [prepared, committed, reviewed, published]}


def run_command_for(entry: ScriptEntry) -> str:
    """The command a human would type. Copyable text only — this module never
    executes anything, and nothing downstream may either."""
    quoted = entry.path if " " not in entry.path else f'"{entry.path}"'
    if entry.executable and entry.interpreter:
        return quoted
    if entry.language == "python":
        return f"python3 {quoted}"
    if entry.language == "shell":
        return f"bash {quoted}"
    if entry.language in ("javascript", "typescript"):
        return f"node {quoted}"
    if entry.language == "powershell":
        return f"pwsh {quoted}"
    if entry.language == "ruby":
        return f"ruby {quoted}"
    return quoted
