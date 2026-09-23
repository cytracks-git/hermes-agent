"""Scripts library plugin — read-only REST routes, mounted at /api/plugins/scripts-library/.

Every route here answers a question about files that already exist on disk. There
is deliberately no route that runs, writes, uploads or deletes anything: the
router is built with GET handlers only, so "read-only" is a property of the
surface rather than a promise in a docstring.

Two boundaries are worth stating because they are what make the surface safe:

**No caller can name a path.** ``/scripts/{script_id}`` takes an opaque id, which
the handler resolves against a freshly scanned catalogue. A path that the scan
did not already accept simply has no id, so directory traversal and credential
reads are not filtered — they are unrepresentable.

**Catalogued code is never imported.** Documentation comes from
``hermes_cli.scripts_library``, which parses text (``ast.parse`` builds a tree
without executing it). Importing a catalogued script to read its ``__doc__``
would execute it, which is exactly the thing a read-only catalogue must not do.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from hermes_cli import scripts_library as sl
from hermes_cli.scripts_library_vcs import repo_root_for

log = logging.getLogger(__name__)

router = APIRouter()

# A scan walks the filesystem and shells out to git, so a dashboard that polls
# must not turn into a disk storm. One short TTL cache, keyed by the resolved
# Hermes home so two profiles never read each other's catalogue.
_CACHE_TTL_SECONDS = 20.0
_cache: Dict[str, Any] = {}
_cache_lock = threading.Lock()


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home())


def _repo_root() -> Optional[Path]:
    """The checkout Hermes itself runs from, so its ``scripts/`` tree is
    catalogued without the user configuring anything."""
    try:
        return repo_root_for(Path(__file__).resolve())
    except Exception:  # pragma: no cover - defensive: git resolution is best-effort
        return None


def _config() -> Dict[str, Any]:
    try:
        from hermes_cli.config_effective import load_user_config_effective

        return load_user_config_effective() or {}
    except Exception as exc:
        log.warning("scripts-library: could not read config: %s", exc)
        return {}


def _scan(force: bool = False) -> sl.ScanResult:
    home = _hermes_home()
    key = str(home)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and not force and cached["expires_at"] > now:
            return cached["result"]

    result = sl.scan(hermes_home=home, repo_root=_repo_root(), config=_config())

    with _cache_lock:
        _cache[key] = {"expires_at": time.monotonic() + _CACHE_TTL_SECONDS, "result": result}
    return result


def _entry_or_404(script_id: str) -> sl.ScriptEntry:
    for entry in _scan().entries:
        if entry.id == script_id:
            return entry
    # A forced rescan covers the one honest miss: a script created since the
    # last cached scan. Still 404 afterwards means the id names nothing.
    for entry in _scan(force=True).entries:
        if entry.id == script_id:
            return entry
    raise HTTPException(status_code=404, detail="script not found")


def _matches(entry: sl.ScriptEntry, needle: str) -> bool:
    return needle in " ".join(
        (entry.name, entry.purpose, entry.category, entry.relpath, entry.language, entry.root_label)
    ).lower()


@router.get("/catalog")
def get_catalog(
    q: Optional[str] = Query(None, description="Free-text filter over name, purpose, category and path"),
    language: Optional[str] = Query(None, description="Filter by detected language"),
    root: Optional[str] = Query(None, description="Filter by root id"),
    refresh: bool = Query(False, description="Bypass the short scan cache"),
) -> Dict[str, Any]:
    """The catalogue: every script found under every configured root.

    ``roots`` is returned alongside ``scripts`` even when the list is empty —
    "no scripts here" and "that directory is gone" are different facts and the
    operator has to be able to tell them apart.
    """
    result = _scan(force=refresh)
    entries = result.entries

    if q and q.strip():
        needle = q.strip().lower()
        entries = [entry for entry in entries if _matches(entry, needle)]
    if language:
        entries = [entry for entry in entries if entry.language == language]
    if root:
        entries = [entry for entry in entries if entry.root_id == root]

    return {
        "scripts": [entry.to_dict() for entry in entries],
        "roots": [
            {
                "id": item.id,
                "label": item.label,
                "path": item.path,
                "origin": item.origin,
                "exists": item.exists,
                "error": item.error,
            }
            for item in result.roots
        ],
        "languages": sorted({entry.language for entry in result.entries}),
        "total": len(result.entries),
        "matched": len(entries),
        "errors": result.errors,
        "truncated": result.truncated,
        "scanned_at": result.scanned_at,
    }


@router.get("/scripts/{script_id}")
def get_script(script_id: str) -> Dict[str, Any]:
    """Full detail for one catalogued script: documentation, parsed sections,
    the copyable run command, git facts and the measured lifecycle."""
    entry = _entry_or_404(script_id)
    return sl.detail_for(entry)


@router.get("/scripts/{script_id}/source")
def get_source(
    script_id: str,
    max_bytes: int = Query(sl.MAX_DOC_BYTES, ge=1024, le=sl.MAX_FILE_BYTES),
) -> Dict[str, Any]:
    """The script's own text, bounded and truncation-flagged.

    Reading the source of a file already in the catalogue is what "understand
    how it works" means; the id gate above is what keeps it from becoming a
    general file-read endpoint.
    """
    entry = _entry_or_404(script_id)
    path = Path(entry.path)
    try:
        with path.open("rb") as handle:
            raw = handle.read(max_bytes + 1)
    except OSError as exc:
        raise HTTPException(status_code=404, detail=f"cannot read script: {exc}") from exc

    truncated = len(raw) > max_bytes
    raw = raw[:max_bytes]
    if b"\0" in raw:
        raise HTTPException(status_code=415, detail="file is not text")

    return {
        "id": entry.id,
        "name": entry.name,
        "language": entry.language,
        "content": raw.decode("utf-8", "replace"),
        "truncated": truncated,
        "bytes": len(raw),
    }


@router.get("/health")
def get_health() -> Dict[str, Any]:
    """Whether the catalogue can be built at all, and what is in the way.

    Used by the UI to distinguish "nothing configured yet" from "the scan
    failed", which are different problems with different fixes.
    """
    result = _scan()
    missing: List[str] = [item.label for item in result.roots if not item.exists]
    return {
        "ok": bool(result.entries) or not result.errors,
        "roots_total": len(result.roots),
        "roots_missing": missing,
        "scripts": len(result.entries),
        "errors": result.errors,
        "truncated": result.truncated,
    }
