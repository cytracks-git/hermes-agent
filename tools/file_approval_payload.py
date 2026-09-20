"""Prepara bytes e diffs sem tocar os alvos da aprovação persistente.

O compilador V4A existente opera sobre um buffer: seu resultado, nunca o patch
original, é o conteúdo autorizado. Não existe reinterpretação depois do gesto.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path

from tools import file_state
from tools.file_operations_common import ReadResult, WriteResult

MAX_PAYLOAD_BYTES = 1024 * 1024
MAX_DIFF_BYTES = 32 * 1024


def digest(data: bytes | None) -> str | None:
    return hashlib.sha256(data).hexdigest() if data is not None else None


def read_bytes(path: str) -> bytes | None:
    try:
        # Não bloquear a ferramenta em FIFO/dispositivo nem carregar bytes sem teto.
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb", buffering=0) as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError(f"Approval target is not a regular file: {path}")
            data = stream.read(MAX_PAYLOAD_BYTES + 1)
            if len(data) > MAX_PAYLOAD_BYTES:
                raise ValueError("Approval target exceeds the 1 MiB limit")
            return data
    except FileNotFoundError:
        return None


def snapshot(path_input: str, task_id: str) -> dict:
    from tools.file_tools_paths import _expand_tilde, _resolve_base_dir
    raw = _expand_tilde(path_input)
    absolute = raw if os.path.isabs(raw) else os.path.join(str(_resolve_base_dir(task_id)), raw)
    real = os.path.realpath(absolute)
    linked = os.path.islink(absolute)
    data = read_bytes(real)
    return {"path_input": path_input, "path_absolute": absolute, "path_real": real,
            "is_symlink": linked, "symlink_to": os.readlink(absolute) if linked else None,
            "pre_sha256": digest(data), "pre_size": len(data) if data is not None else None}


def normalize_content(content: str, original: bytes | None) -> str:
    from tools.file_operations_common import _normalize_line_endings, _has_bom, _UTF8_BOM
    if original and b"\r\n" in original:
        content = _normalize_line_endings(content, "\r\n")
    if original and original.startswith(b"\xef\xbb\xbf") and not _has_bom(content):
        content = _UTF8_BOM + content
    return content


class ContentPlan:
    """Buffer da fase de preparação; o parser nativo não recebe acesso de escrita."""

    def __init__(self, originals: dict[str, bytes | None]):
        self.originals = originals
        self.contents = {p: b.decode("utf-8-sig") if b is not None else None
                         for p, b in originals.items()}

    def read_file_raw(self, path: str) -> ReadResult:
        content = self.contents[path]
        return ReadResult(content=content or "", error="File not found" if content is None else None)

    def write_file(self, path: str, content: str, pre_content=None) -> WriteResult:
        normalized = normalize_content(content, self.originals[path])
        self.contents[path] = normalized
        return WriteResult(bytes_written=len(normalized.encode("utf-8")))


def prepare_payload(op: str, paths: list[str], reasons: list[str], task_id: str, **args) -> dict:
    from tools.fuzzy_match import fuzzy_find_and_replace
    from tools.patch_parser import OperationType, parse_v4a_patch, apply_v4a_operations
    targets = [snapshot(p, task_id) for p in dict.fromkeys(paths)]
    if len({t["path_real"] for t in targets}) != len(targets):
        raise ValueError("Approval targets alias the same file; use one path per file")
    originals = {t["path_input"]: read_bytes(t["path_real"]) for t in targets}
    if any(digest(originals[t["path_input"]]) != t["pre_sha256"] for t in targets):
        raise ValueError("Approval target changed while preparing the operation")
    plan = ContentPlan(originals)
    if op == "write_file":
        plan.write_file(paths[0], args["content"])
    elif op == "patch":
        old = plan.read_file_raw(paths[0])
        if old.error:
            raise ValueError(old.error)
        content, count, _, error = fuzzy_find_and_replace(
            old.content, args["old_string"], args["new_string"], args["replace_all"])
        if error or not count:
            raise ValueError(error or "Patch has no matching text")
        plan.write_file(paths[0], content)
    else:
        operations, error = parse_v4a_patch(args["patch"])
        if error:
            raise ValueError(error)
        # O contrato autoriza post_blob escrito, não exclusão ou rename. Recusa
        # explícita antes de criar pendência, sem interpretar ausência como arquivo vazio.
        if any(item.operation not in {OperationType.ADD, OperationType.UPDATE} for item in operations):
            raise ValueError("Persistent approval supports Add/Update only; Delete/Move needs a separate human operation")
        result = apply_v4a_operations(operations, plan)
        if result.error:
            raise ValueError(result.error)
    for target in targets:
        path = target["path_input"]
        before = originals[path]
        content = plan.contents[path]
        if content is None:
            raise ValueError(f"No proposed content for {path}")
        post = content.encode("utf-8")
        before_text = before.decode("utf-8") if before is not None else ""
        diff = "".join(difflib.unified_diff(before_text.splitlines(keepends=True),
                          content.splitlines(keepends=True), fromfile=path, tofile=path))
        raw_diff = diff.encode("utf-8")
        if len(raw_diff) > MAX_DIFF_BYTES:
            diff = raw_diff[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore") + "\n[Diff truncated; review full proposed content]\n"
        target.update(post_sha256=digest(post), post_size=len(post), post_blob=content,
                      diff_unified=diff)
    payload = {"op": op, "targets": targets, "reasons": reasons}
    from hermes_cli.kanban_db_approvals import canonical_payload_json
    if len(canonical_payload_json(payload).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("Approval payload exceeds the 1 MiB limit; no request was created")
    return payload


def revalidate(payload: dict) -> None:
    for target in payload["targets"]:
        path = target["path_absolute"]
        linked = os.path.islink(path)
        if (os.path.realpath(path) != target["path_real"] or linked != target["is_symlink"]
                or (os.readlink(path) if linked else None) != target["symlink_to"]):
            raise ValueError(f"Approval obsolete: symlink changed for {path}")
        if digest(read_bytes(target["path_real"])) != target["pre_sha256"]:
            raise ValueError(f"Approval obsolete: preimage changed for {path}")
        post = target["post_blob"].encode("utf-8")
        if digest(post) != target["post_sha256"] or len(post) != target["post_size"]:
            raise ValueError("Approval payload content hash mismatch")


@contextmanager
def target_locks(payload: dict):
    # Arquivo lateral estável: o inode do alvo é trocado pela escrita atômica.
    # Local ao alvo, não ao perfil/board, para serializar também dois boards.
    with ExitStack() as stack:
        for path in sorted({t["path_real"] for t in payload["targets"]}):
            parent = Path(path).parent
            parent.mkdir(parents=True, exist_ok=True)
            lock = parent / (".hermes-approval-" + hashlib.sha256(path.encode()).hexdigest() + ".lock")
            stream = stack.enter_context(open(lock, "a+b"))
            if os.name == "posix":
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            else:
                import portalocker
                portalocker.lock(stream, portalocker.LOCK_EX)
            stack.enter_context(file_state.lock_path(path))
        yield
