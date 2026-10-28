"""The dashboard dispatch nudge honours the same caps as the embedded dispatcher.

Measured in the field: the dashboard ``POST /dispatch`` called ``dispatch_once``
with only ``max_spawn=8`` and spawned five workers in one call on a host whose
``kanban.max_in_progress`` was 2. The embedded dispatcher then sat at the host
cap for ticks on end and logged "dispatcher stuck" for work it never had budget
for. Both entry points now read caps through ``resolve_dispatch_caps`` and the
stuck warning names the cap that held the tick.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_dispatch as kbd


@pytest.fixture
def kanban_home(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb.init_db()
    return home


def _dashboard_plugin_api():
    mod_name = "hermes_dashboard_plugin_kanban_dispatch_caps_test"
    if mod_name not in sys.modules:
        plugin_file = Path(__file__).resolve().parents[2] / "plugins" / "kanban" / "dashboard" / "plugin_api.py"
        spec = importlib.util.spec_from_file_location(mod_name, plugin_file)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[mod_name]


def _seed_ready(conn, n: int) -> None:
    for i in range(n):
        kb.create_task(conn, title=f"ready-{i}", assignee="alice")


def _spawn_counter(spawns: list):
    def fake_spawn(task, workspace, board=None):
        spawns.append(task.id)
        return 42
    return fake_spawn


def test_dashboard_nudge_respects_max_in_progress(kanban_home, monkeypatch, all_assignees_spawnable):
    """Five ready tasks, host cap 2: the nudge spawns at most 2."""
    api = _dashboard_plugin_api()
    spawns: list = []
    monkeypatch.setattr(kbd, "_default_spawn", _spawn_counter(spawns))
    monkeypatch.setattr(
        kbd, "resolve_dispatch_caps",
        lambda cfg=None: {"max_spawn": None, "max_in_progress": 2,
                          "max_in_progress_per_profile": None, "default_assignee": None},
    )
    with kbc.connect() as conn:
        _seed_ready(conn, 5)

    out = api.dispatch(dry_run=False, max_n=8, board=None)

    assert len(spawns) == 2, spawns
    assert len(out["spawned"]) == 2
    with kbc.connect() as conn:
        running = conn.execute("SELECT COUNT(*) FROM tasks WHERE status='running'").fetchone()[0]
    assert running == 2


def test_dashboard_nudge_max_only_tightens_the_configured_cap(kanban_home, monkeypatch, all_assignees_spawnable):
    """``?max=`` from the UI never lifts ``kanban.max_spawn``: min() of both wins."""
    api = _dashboard_plugin_api()
    seen: dict = {}

    def fake_dispatch_once(conn, **kwargs):
        seen.update(kwargs)
        return kb.DispatchResult()

    monkeypatch.setattr(kbd, "dispatch_once", fake_dispatch_once)
    monkeypatch.setattr(
        kbd, "resolve_dispatch_caps",
        lambda cfg=None: {"max_spawn": 3, "max_in_progress": 4,
                          "max_in_progress_per_profile": 1, "default_assignee": "bob"},
    )
    api.dispatch(dry_run=True, max_n=8, board=None)
    assert seen["max_spawn"] == 3
    assert seen["max_in_progress"] == 4
    assert seen["max_in_progress_per_profile"] == 1
    assert seen["default_assignee"] == "bob"

    api.dispatch(dry_run=True, max_n=1, board=None)
    assert seen["max_spawn"] == 1


def test_positive_control_nudge_spawns_when_under_cap(kanban_home, monkeypatch, all_assignees_spawnable):
    """The cap must not refuse everyone: 1 ready task under cap 2 spawns."""
    api = _dashboard_plugin_api()
    spawns: list = []
    monkeypatch.setattr(kbd, "_default_spawn", _spawn_counter(spawns))
    monkeypatch.setattr(
        kbd, "resolve_dispatch_caps",
        lambda cfg=None: {"max_spawn": None, "max_in_progress": 2,
                          "max_in_progress_per_profile": None, "default_assignee": None},
    )
    with kbc.connect() as conn:
        _seed_ready(conn, 1)
    api.dispatch(dry_run=False, max_n=None, board=None)
    assert len(spawns) == 1


def test_resolve_dispatch_caps_reads_kanban_section():
    caps = kbd.resolve_dispatch_caps({"kanban": {
        "max_spawn": "4", "max_in_progress": 2,
        "max_in_progress_per_profile": 0, "default_assignee": " bob ",
    }})
    assert caps == {"max_spawn": 4, "max_in_progress": 2,
                    "max_in_progress_per_profile": None, "default_assignee": "bob"}


def test_resolve_dispatch_caps_falls_back_to_derived_default(monkeypatch):
    monkeypatch.setattr(kbd, "derive_default_max_in_progress", lambda sample=None: 3)
    caps = kbd.resolve_dispatch_caps({"kanban": {}})
    assert caps["max_in_progress"] == 3


def test_describe_suppression_names_the_cap_that_held_the_tick(kanban_home, all_assignees_spawnable):
    """A tick that spawned 0 because the host is at cap is steady state; the
    stuck warning must say so instead of a bare zero."""
    with kbc.connect() as conn:
        for i in range(2):
            tid = kb.create_task(conn, title=f"busy-{i}", assignee="alice")
            assert kb.claim_task(conn, tid) is not None
        _seed_ready(conn, 1)
        res = kbd.dispatch_once(conn, spawn_fn=_spawn_counter([]), max_in_progress=2)
    assert res.spawned == []
    assert res.capped == "max_in_progress=2 running=2"
    assert "capped(max_in_progress=2 running=2)" in kbd.describe_suppression([res])

    # Positive control: an uncapped tick reports nothing held back.
    with kbc.connect() as conn:
        _seed_ready(conn, 1)
        res2 = kbd.dispatch_once(conn, spawn_fn=_spawn_counter([]))
    assert res2.capped is None
    assert kbd.describe_suppression([res2]) == ""
