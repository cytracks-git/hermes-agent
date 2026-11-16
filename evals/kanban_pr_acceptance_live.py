"""Local HTTP/lifecycle probe; no external GitHub writes or inference.
Run: python evals/kanban_pr_acceptance_live.py ROOT

The probe creates fixture tasks (completion_contract='acme/repo', PR pull/7).
Run from inside a kanban worker it inherits the board pins
(HERMES_KANBAN_DB/BOARD/HOME) and a TMPDIR under the real HERMES_HOME, so
without isolation those fixtures land on the live board. The block below
moves every write into a disposable sandbox and exits 2 (fail closed) if the
resolved board still points at a protected root.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ISOLATION_FAILED = 2

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
from hermes_constants import get_default_hermes_root


def _protected_roots():
    # Raizes do ambiente herdado: raiz Hermes, HERMES_HOME, raiz do kanban e
    # pasta do DB pinado. Nada do eval pode resolver para dentro delas.
    roots = {get_default_hermes_root()}
    for var in ('HERMES_HOME', 'HERMES_KANBAN_HOME'):
        value = os.environ.get(var, '').strip()
        if value:
            roots.add(Path(value).expanduser())
    pinned_db = os.environ.get('HERMES_KANBAN_DB', '').strip()
    if pinned_db:
        roots.add(Path(pinned_db).expanduser().parent)
    return [r.resolve() for r in roots]


def _inside(path, roots):
    path = Path(path).resolve()
    return any(path == r or path.is_relative_to(r) for r in roots)


def _fail_closed(reason):
    print(json.dumps({'isolation': 'failed', 'reason': reason}), file=sys.stderr)
    sandbox = globals().get('SANDBOX')
    if sandbox is not None:
        shutil.rmtree(sandbox, ignore_errors=True)
    sys.exit(ISOLATION_FAILED)


PROTECTED = _protected_roots()
# TMPDIR do worker fica sob o HERMES_HOME real; um HERMES_HOME temporario ali
# faz get_default_hermes_root() voltar para a raiz real.
base = next((c for c in (tempfile.gettempdir(), '/tmp') if not _inside(c, PROTECTED)), None)
if base is None:
    _fail_closed('no temp dir outside the protected Hermes roots')
SANDBOX = Path(tempfile.mkdtemp(prefix='hermes-pr-live-sandbox-', dir=base)).resolve()
for var in [v for v in os.environ if v.startswith('HERMES_KANBAN_')]:
    del os.environ[var]
os.environ['HERMES_HOME'] = str(SANDBOX / 'home')
os.environ['HERMES_KANBAN_HOME'] = str(SANDBOX / 'kanban-home')
os.environ['TMPDIR'] = str(SANDBOX)
tempfile.tempdir = str(SANDBOX)


def _assert_isolated(db_path):
    if _inside(db_path, PROTECTED) or not _inside(db_path, [SANDBOX]):
        _fail_closed(f'kanban db {db_path} is outside the sandbox {SANDBOX}')


os.environ.pop('HERMES_DELEGATED_CHILD_CONTEXT', None)
import pytest
from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect
import inspect

_assert_isolated(kb.kanban_db_path())

def create(conn, title):
    if 'completion_contract' in inspect.signature(kb.create_task).parameters:
        return kb.create_task(conn, title=title, completion_contract='acme/repo')
    tid = kb.create_task(conn, title=title)
    if 'completion_contract' not in {r[1] for r in conn.execute('PRAGMA table_info(tasks)')}:
        conn.execute('ALTER TABLE tasks ADD COLUMN completion_contract TEXT')
    conn.execute('UPDATE tasks SET completion_contract=? WHERE id=?', ('acme/repo', tid))
    conn.commit()
    return tid

fixture_root = Path(sys.argv[2]) if len(sys.argv) > 2 else root
spec = importlib.util.spec_from_file_location('http_fixture', fixture_root / 'tests/hermes_cli/test_kanban_pr_acceptance.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
patch = pytest.MonkeyPatch()
with tempfile.TemporaryDirectory(prefix='hermes-pr-live-') as home:
    setup = fixture.github.__wrapped__(Path(home), patch)
    state = next(setup)
    reports = []
    try:
        _assert_isolated(kb.kanban_db_path())
        with connect() as conn:
            for outcome in ('failure', 'cancelled', 'timed_out', 'success'):
                state.update(conclusion=outcome)
                tid = create(conn, 'PR acceptance live')
                accepted = kb.complete_task(conn, tid, metadata={'published_pr': 'https://github.com/acme/repo/pull/7'})
                row = conn.execute("SELECT payload FROM task_events WHERE task_id=? AND kind='pr_acceptance' ORDER BY id DESC", (tid,)).fetchone()
                receipt = json.loads(row[0]) if row else None
                reports.append({'case': outcome, 'accepted': accepted, 'status': kb.get_task(conn, tid).status, 'receipt': receipt})
            for outcome in (('success', 'failure') if 'completion_contract' in inspect.signature(kb.create_task).parameters else ()):
                tid = kb.create_task(conn, title='Concurrent ownership', completion_contract='acme/repo')
                owner = kb.claim_task(conn, tid)
                run_id = owner.current_run_id
                def reclaim():
                    with connect() as other:
                        kb.block_task(other, tid, reason='Reassigned during acceptance')
                        kb.unblock_task(other, tid)
                        state['replacement'] = kb.claim_task(other, tid).current_run_id
                state.update(conclusion=outcome, race=reclaim)
                accepted = kb.complete_task(conn, tid, expected_run_id=run_id, metadata={'published_pr': 'https://github.com/acme/repo/pull/7'})
                reports.append({'case': 'CAS-'+outcome, 'accepted': accepted, 'run_id': kb.get_task(conn, tid).current_run_id,
                    'receipts': conn.execute("SELECT count(*) FROM task_events WHERE task_id=? AND kind='pr_acceptance'", (tid,)).fetchone()[0]})
                del state['race']
        print(json.dumps({'reports': reports, 'requests': state['requests']}, indent=2))
    finally:
        try:
            next(setup)
        except StopIteration:
            pass
        patch.undo()
        shutil.rmtree(SANDBOX, ignore_errors=True)
