"""Integra a ferramenta real ao journal; nenhuma decisão humana nasce aqui."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_approvals as journal
from hermes_cli.kanban_db_connect import connect
from hermes_cli.kanban_db_dispatch import _process_fingerprint
from tools.file_approval_payload import digest, prepare_payload, read_bytes, revalidate, target_locks


def _identity_matches(request) -> bool:
    from agent.delegation_context import owned_kanban_task
    from hermes_constants import get_hermes_home
    from tools.approval_context import get_current_session_key
    return (request.task_id == owned_kanban_task()
            and request.run_id == int(os.environ.get("HERMES_KANBAN_RUN_ID", "0"))
            and request.profile_home == str(get_hermes_home().resolve())
            and request.session_key == get_current_session_key()
            and request.claim_lock == os.environ.get("HERMES_KANBAN_CLAIM_LOCK")
            and request.created_by_pid == os.getpid()
            and request.created_by_started_at == str(_process_fingerprint(os.getpid())))


def _create_and_pause(conn, payload):
    from agent.delegation_context import owned_kanban_task
    from hermes_constants import get_hermes_home
    from tools.approval_context import get_current_session_key
    task_id = owned_kanban_task()
    with kb.write_txn(conn):
        task = kb.get_task(conn, task_id)
        run_id = int(os.environ.get("HERMES_KANBAN_RUN_ID", "0"))
        fingerprint = _process_fingerprint(os.getpid())
        identity = conn.execute("SELECT worker_started_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if (task is None or task.status != "running" or task.current_run_id != run_id
                or not task.claim_lock or task.claim_lock != os.environ.get("HERMES_KANBAN_CLAIM_LOCK")
                or task.worker_pid != os.getpid() or not fingerprint
                or str(identity["worker_started_at"]) != str(fingerprint) or not task.workspace_path):
            raise ValueError("Approval requires the current dispatcher-owned run and worker identity")
        request = journal.create_request(
            conn, task_id=task_id, run_id=run_id, claim_lock=task.claim_lock,
            profile_home=str(get_hermes_home().resolve()), session_key=get_current_session_key(),
            workspace_path=os.path.realpath(task.workspace_path), created_by_pid=os.getpid(),
            created_by_started_at=str(fingerprint), payload=payload)
        if not kb.pause_for_approval(conn, task_id, request_id=request.request_id,
                                    request_hash=request.request_hash, expected_run_id=run_id,
                                    targets=[t["path_real"] for t in payload["targets"]]):
            raise ValueError("Approval pause lost the current run")
        return request


def _stage(path: str, data: bytes) -> str:
    fd, name = tempfile.mkstemp(prefix=".hermes-approved-", dir=str(Path(path).parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if os.path.exists(path):
            os.chmod(name, os.stat(path).st_mode & 0o777)
        return name
    except BaseException:
        os.unlink(name)
        raise


def _write_exact(payload, file_ops) -> dict:
    targets = payload["targets"]
    before = {t["path_real"]: read_bytes(t["path_real"]) for t in targets}
    staged, applied = {}, []
    try:
        # Validação de todos os candidatos antes de trocar qualquer alvo.
        for target in targets:
            path, content = target["path_real"], target["post_blob"]
            refusal = file_ops._fail_closed_syntax_error(path, Path(path).suffix.lower(), content)
            if refusal is not None:
                raise ValueError(refusal.error)
            staged[path] = _stage(path, content.encode("utf-8"))
        for target in targets:
            path = target["path_real"]
            os.replace(staged.pop(path), path)
            applied.append(path)
            if digest(read_bytes(path)) != target["post_sha256"]:
                raise OSError(f"Post-write verification failed for {path}")
    except BaseException:
        # Falha recuperável não deixa metade do patch aplicada. Crash do SO não
        # é transação de filesystem: o journal consumido impede replay e exige inspeção.
        for path in reversed(applied):
            original = before[path]
            if original is None:
                os.unlink(path)
            else:
                os.replace(_stage(path, original), path)
        raise
    finally:
        for name in staged.values():
            os.unlink(name)
    return {"success": True, "verified": True,
            "files_modified": [t["path_real"] for t in targets],
            "diff": "\n".join(t["diff_unified"] for t in targets)}


def _apply_granted_locked(conn, request_id: str, file_ops) -> dict:
    request = journal.get_request(conn, request_id)
    if request is None or not _identity_matches(request):
        raise ValueError("Approval origin/profile/run does not match this worker")
    payload = request.payload
    if journal.request_hash(payload) != request.request_hash:
        raise ValueError("Approval request hash mismatch")
    with target_locks(payload):
        # Commit antes da escrita: crash não devolve consumed para granted.
        with kb.write_txn(conn):
            if not journal.consume_grant(conn, request_id):
                raise ValueError("Approval has already been consumed or was not granted")
        try:
            with kb.write_txn(conn):
                task = kb.get_task(conn, request.task_id)
                if (task is None or task.status != "waiting_approval"
                        or task.current_run_id != request.run_id
                        or os.path.realpath(task.workspace_path or "") != request.workspace_path):
                    raise ValueError("Approval no longer belongs to the waiting run")
                revalidate(payload)
                # Reserva a retomada sob a mesma txn, invisível até a escrita e
                # recibo. CAS falho jamais escreve; não há running sem identidade.
                if not kb.resume_from_pause(
                        conn, request.task_id, request_id=request_id,
                        claim_lock=request.claim_lock, worker_pid=request.created_by_pid,
                        worker_started_at=request.created_by_started_at, expected_run_id=request.run_id):
                    raise ValueError("Approval resume lost its compare-and-swap")
                result = _write_exact(payload, file_ops)
                if not journal.mark_applied(conn, request_id):
                    raise RuntimeError("Approval write receipt could not be recorded")
                result["approval_request_id"] = request_id
                return result
        except Exception as exc:
            with kb.write_txn(conn):
                journal.mark_obsolete(conn, request_id)
                kb.end_approval_wait(conn, request.task_id, request_id=request_id,
                                     expected_run_id=request.run_id, outcome="obsolete", reason=str(exc))
            raise


def _admission_refusal(conn, config, board) -> str:
    """Qual teto barrou a admissão, avaliado DENTRO do mesmo lock.

    Só é chamado depois de ``_tick_spawn_budget`` recusar, com o lock do
    dispatcher ainda na mão: ninguém mais escreve nesse intervalo, logo a
    contagem aqui é o mesmo retrato que produziu a recusa — não um palpite
    refeito depois. Ordem igual à do dispatcher (board, host, memória) para
    nomear o primeiro teto que fecha, que é o que o operador precisa liberar.
    """
    from hermes_cli.kanban_db_dispatch import (
        _memory_pressure_level, count_running_tasks, count_running_tasks_other_boards,
        resolve_max_in_progress,
    )
    from hermes_cli import kanban_approval_diagnostics as diag
    max_spawn = config.get("max_spawn")
    max_in_progress = resolve_max_in_progress(config.get("max_in_progress"))
    running = count_running_tasks(conn) if (max_spawn is not None or max_in_progress is not None) else 0
    if max_spawn is not None and running >= max_spawn:
        return diag.BOARD_CAPACITY
    if max_in_progress is not None and running + count_running_tasks_other_boards(board) >= max_in_progress:
        return diag.HOST_CAPACITY
    if _memory_pressure_level() == "critical":
        return diag.MEMORY_PRESSURE
    # Nenhum teto fecha agora: a recusa foi por corrida (a pressão cedeu, ou uma
    # vaga abriu entre a decisão e esta leitura). Dizer "não observado" em vez de
    # escolher um culpado plausível.
    return diag.RESUME_REASON_NOT_YET_OBSERVED


def apply_granted(conn, request_id: str, file_ops) -> tuple[dict | None, str | None]:
    """``(resultado, motivo_da_recusa)``. Exatamente um dos dois é ``None``.

    O motivo nasce aqui, sob o lock que produziu a recusa, porque este é o único
    ponto que conhece a causa: quem lê depois (painel, worker, revisor) veria
    apenas ``granted`` parado e teria de adivinhar entre cinco causas distintas.
    """
    from hermes_cli.kanban_db_connect import _dispatch_tick_lock
    from hermes_cli.kanban_db_dispatch import (
        DispatchResult, _tick_spawn_budget, resolve_max_in_progress,
    )
    from hermes_cli.config import load_config_readonly
    from hermes_cli import kanban_approval_diagnostics as diag
    # Mesmo lock e mesma admissão do dispatcher; a retomada ocupa uma vaga.
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    with _dispatch_tick_lock(Path(db_path)) as held:
        if not held:
            return None, diag.DISPATCHER_LOCK
        config = (load_config_readonly() or {}).get("kanban", {})
        board = os.environ.get("HERMES_KANBAN_BOARD")
        allowed, _ = _tick_spawn_budget(
            conn, DispatchResult(), max_spawn=config.get("max_spawn"),
            max_in_progress=resolve_max_in_progress(config.get("max_in_progress")),
            board=board)
        if not allowed:
            return None, _admission_refusal(conn, config, board)
        cap = config.get("max_in_progress_per_profile")
        request = journal.get_request(conn, request_id)
        task = kb.get_task(conn, request.task_id) if request else None
        if isinstance(cap, int) and not isinstance(cap, bool) and cap > 0 and task:
            running = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='running' AND assignee=?",
                                   (task.assignee,)).fetchone()[0]
            if running >= cap:
                return None, diag.PROFILE_CAPACITY
        return _apply_granted_locked(conn, request_id, file_ops), None


def _wait(conn, request, file_ops) -> dict:
    from hermes_cli import kanban_approval_diagnostics as diag
    delay = 0.1
    while True:
        current = journal.get_request(conn, request.request_id)
        if current is None:
            raise ValueError("Approval request disappeared; no write performed")
        if current.state == journal.PENDING:
            # Observação idempotente: repetir o mesmo poll não grava linha nova.
            diag.record_progress(
                conn, task_id=current.task_id, run_id=current.run_id,
                request_id=current.request_id, phase=diag.AWAITING_HUMAN,
                reason_code=diag.HUMAN_DECISION_PENDING)
        if current.state == journal.GRANTED:
            result, refusal = apply_granted(conn, current.request_id, file_ops)
            if result is not None:
                return result
            diag.record_progress(
                conn, task_id=current.task_id, run_id=current.run_id,
                request_id=current.request_id, phase=diag.AWAITING_ADMISSION,
                reason_code=refusal or diag.RESUME_REASON_NOT_YET_OBSERVED)
        if current.state not in (journal.PENDING, journal.GRANTED):
            raise ValueError(f"Approval {current.state}; no write performed")
        time.sleep(delay)
        delay = min(delay * 1.5, 2.0)


def handle_worker_write(paths: list[str], *, op: str, task_id: str,
                        cross_profile: bool, session_id=None, **args) -> str | None:
    from agent.delegation_context import owned_kanban_task
    from agent.file_safety import get_write_denied_error
    from tools import file_tools as ft
    from tools import file_tools_write_guards as guards
    if not owned_kanban_task():
        return None
    reasons = [r for p in paths if (r := guards._protected_instruction_reason(p, task_id))]
    if not reasons:
        return None
    conn = None
    request = None
    try:
        file_ops = ft._get_file_ops(task_id)
        if not ft._file_ops_uses_host_paths(file_ops):
            raise ValueError("Persistent approval requires local file targets; remote target identity is unavailable")
        for path in paths:
            error = (guards._check_sensitive_path(path, task_id)
                     or guards._check_binary_document_write(path, task_id)
                     or get_write_denied_error(str(ft._resolve_path_for_task(path, task_id)))
                     or (None if cross_profile else guards._check_cross_profile_path(path, task_id)))
            if error:
                raise ValueError(error)
        error = guards._check_approval_required_write(paths, task_id)
        if error:
            raise ValueError(error)
        if op == "write_file":
            if guards._is_internal_file_tool_content(args["content"]):
                raise ValueError("Refusing to write internal read_file display text")
            error = guards._stale_overwrite_blocker(paths[0], str(ft._resolve_path_for_task(paths[0], task_id)), task_id)
            if error:
                raise ValueError(error)
        payload = prepare_payload(op, paths, reasons, task_id, **args)
        conn = connect(kb.kanban_db_path())
        with target_locks(payload):
            revalidate(payload)
            request = _create_and_pause(conn, payload)
        result = _wait(conn, request, file_ops)
        resolved = {t["path_input"]: t["path_real"] for t in payload["targets"]}
        ft._note_edited(task_id, paths, resolved, session_id)
        if op == "write_file":
            ft._mark_full_write_baseline(resolved[paths[0]], task_id)
        return json.dumps(result, ensure_ascii=False)
    except Exception as exc:
        if conn is not None and request is not None:
            try:
                with kb.write_txn(conn):
                    if journal.mark_obsolete(conn, request.request_id):
                        kb.end_approval_wait(conn, request.task_id, request_id=request.request_id,
                                             expected_run_id=request.run_id, outcome="obsolete", reason=str(exc))
            except Exception as journal_error:
                return json.dumps({"error": f"BLOCKED: {exc}; approval recovery failed: {journal_error}"})
        return json.dumps({"error": f"BLOCKED: {exc}"}, ensure_ascii=False)
    finally:
        if conn is not None:
            conn.close()
