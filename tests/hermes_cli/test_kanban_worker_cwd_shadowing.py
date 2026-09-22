"""A Hermes checkout in the worker cwd must not shadow the running install.

Kanban workers are spawned as ``python -m hermes_cli.main`` with
``cwd=workspace``. CPython prepends cwd onto ``sys.path`` for ``-m``, so a
workspace that is itself an old/hostile Hermes tree used to load that tree's
``hermes_cli`` / ``cli`` — including a goal-loop that lacked the preflight
75/78 stamp. Isolation is the interpreter ``-P`` flag on the native module
argv, not ``PYTHONSAFEPATH`` (inherited by terminal children) and not a cwd
change (file tools and context files stay in the workspace).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _child_env(home: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["HERMES_HOME"] = str(home)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(REPO_ROOT), existing) if p)
    env.pop("HERMES_DEV", None)
    env.pop("HERMES_BIN", None)
    return env


def _plant_hostile_checkout(ws: Path) -> None:
    """Old/hostile Hermes tree: ``-m hermes_cli.main`` would run THIS, not the install."""
    pkg = ws / "hermes_cli"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("HOSTILE = True\n", encoding="utf-8")
    (pkg / "main.py").write_text(
        "import sys\nprint('HOSTILE_MAIN')\nsys.exit(42)\n",
        encoding="utf-8",
    )
    (ws / "cli.py").write_text(
        "HOSTILE = True\n# old checkout: no _stamp_preflight_turn_result\n",
        encoding="utf-8",
    )


def _isolation_prefix(argv: list[str]) -> list[str]:
    """``python`` + flags that precede ``-m`` on the native worker argv."""
    prefix = [argv[0]]
    for item in argv[1:]:
        if item == "-m":
            break
        prefix.append(item)
    return prefix


def _run(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_hostile_workspace_old_argv_shadows_native_argv_does_not(tmp_path):
    """Mutant (no ``-P``) loads cwd; native argv loads the install and keeps cwd."""
    from hermes_cli import kanban_db_dispatch as kbd

    home = tmp_path / ".hermes"
    home.mkdir()
    ws = tmp_path / "old-checkout"
    ws.mkdir()
    _plant_hostile_checkout(ws)
    (ws / "notes.txt").write_text("workspace stays writable\n", encoding="utf-8")
    env = _child_env(home)

    mutant = _run(
        [sys.executable, "-m", "hermes_cli.main", "--version"],
        cwd=ws,
        env=env,
    )
    assert mutant.returncode == 42, mutant.stderr
    assert "HOSTILE_MAIN" in mutant.stdout
    assert "Hermes Agent" not in mutant.stdout

    argv = kbd._module_hermes_argv()
    assert argv[:2] == [sys.executable, "-P"]
    assert argv[2:4] == ["-m", "hermes_cli.main"]
    native = _run(argv + ["--version"], cwd=ws, env=env)
    combined = native.stdout + native.stderr
    assert native.returncode == 0, combined
    assert "Hermes Agent" in native.stdout
    assert "HOSTILE_MAIN" not in combined

    prefix = _isolation_prefix(argv)
    probe = _run(
        [
            *prefix,
            "-c",
            "import json, os, sys; print(json.dumps({"
            "'cwd': os.getcwd(), "
            "'safe_path': bool(getattr(sys.flags, 'safe_path', 0)), "
            "'path0': sys.path[0] if sys.path else None"
            "}))",
        ],
        cwd=ws,
        env=env,
    )
    assert probe.returncode == 0, probe.stderr
    info = json.loads(probe.stdout)
    assert info["cwd"] == str(ws)
    assert info["safe_path"] is True
    assert info["path0"] not in ("", str(ws))

    marker = ws / "wrote_from_worker.txt"
    write = _run(
        [*prefix, "-c", "open('wrote_from_worker.txt','w',encoding='utf-8').write(__import__('os').getcwd())"],
        cwd=ws,
        env=env,
    )
    assert write.returncode == 0, write.stderr
    assert marker.read_text(encoding="utf-8") == str(ws)
    assert (ws / "notes.txt").read_text(encoding="utf-8") == "workspace stays writable\n"


def test_plain_workspace_native_argv_still_runs(tmp_path):
    """Positive: a normal project workspace (no Hermes package) still boots."""
    from hermes_cli import kanban_db_dispatch as kbd

    home = tmp_path / ".hermes"
    home.mkdir()
    ws = tmp_path / "app"
    ws.mkdir()
    (ws / "AGENTS.md").write_text("# app\n", encoding="utf-8")
    env = _child_env(home)
    native = _run(kbd._module_hermes_argv() + ["--version"], cwd=ws, env=env)
    assert native.returncode == 0, native.stderr
    assert "Hermes Agent" in native.stdout


def test_preflight_from_old_workspace_exits_75_and_78_without_judge(tmp_path):
    """Quota/auth walls born before a turn dict must not feed the Ralph loop.

    The probe is launched with the native isolation flags and ``cwd`` set to an
    old checkout whose ``cli.py`` has no preflight helpers. If cwd still won,
    the import would be the hostile module and the probe would exit 2.
    """
    from hermes_cli import kanban_db_dispatch as kbd

    home = tmp_path / ".hermes"
    home.mkdir()
    ws = tmp_path / "old-checkout"
    ws.mkdir()
    _plant_hostile_checkout(ws)
    env = _child_env(home)
    env["HOSTILE_WS"] = str(ws)
    env["HERMES_KANBAN_TASK"] = "t_preflight"
    env["HERMES_KANBAN_GOAL_MODE"] = "1"
    env["HERMES_KANBAN_GOAL_MAX_TURNS"] = "15"

    probe_path = tmp_path / "preflight_probe.py"
    probe_path.write_text(
        textwrap.dedent(
            """
            import json
            import os
            import sys
            from types import SimpleNamespace

            import cli

            origin = os.path.realpath(getattr(cli, "__file__", "") or "")
            hostile = os.path.realpath(os.environ["HOSTILE_WS"])
            from_cwd = origin == hostile or origin.startswith(hostile + os.sep)
            report = {
                "cli": origin,
                "cwd": os.getcwd(),
                "from_cwd": from_cwd,
                "has_stamp": hasattr(cli, "_stamp_preflight_turn_result"),
                "hostile_flag": bool(getattr(cli, "HOSTILE", False)),
            }
            if report["hostile_flag"] or from_cwd or not report["has_stamp"]:
                print(json.dumps(report))
                raise SystemExit(2)

            from hermes_cli.auth import AuthError
            from hermes_cli.kanban_db import (
                KANBAN_RATE_LIMIT_EXIT_CODE,
                KANBAN_TERMINAL_PROVIDER_EXIT_CODE,
            )
            import hermes_cli.goals as goals

            judges = []
            goals.judge_goal = lambda *a, **k: judges.append("judge") or (
                "continue",
                "empty response (nothing to evaluate)",
                False,
                None,
                False,
            )
            loops = []
            goals.run_kanban_goal_loop = lambda **k: loops.append(k) or {"outcome": "should-not-run"}

            class _Conn:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

            import hermes_cli.kanban_db as kb
            import hermes_cli.kanban_db_connect as kbc

            kbc.connect_closing = lambda: _Conn()
            kb.get_task = lambda conn, tid: SimpleNamespace(
                id=tid, status="running", title="t", body="b",
                goal_mode=True, goal_max_turns=15,
            )
            kb.goal_run_status = lambda conn, tid, run_id: "running"
            kb.block_task = lambda *a, **k: None

            cli._should_seed_interactive = lambda *a, **k: False
            cli._collect_query_images = lambda q, i: (q, [])
            cli._collect_kanban_task_images = lambda imgs: []
            cli._finalize_single_query = lambda c: None

            obj = SimpleNamespace(
                _last_runtime_error=AuthError(
                    "Anthropic credentials are rate-limited for claude-opus-5; "
                    "other Claude models remain available",
                    code="rate_limit",
                    retryable=True,
                ),
                _last_turn_result=None,
            )
            cli._stamp_preflight_turn_result(obj)
            code75 = cli._single_query_exit_code(obj._last_turn_result)
            allowed75 = cli._kanban_goal_loop_allowed(obj._last_turn_result)

            stub = SimpleNamespace(
                _single_query_mode=False,
                _claim_active_session=lambda *a, **k: True,
                console=SimpleNamespace(print=lambda *a, **k: None),
                _show_security_advisories=lambda: None,
                chat=lambda *a, **k: "",
                _print_exit_summary=lambda **k: None,
                _last_turn_result={
                    "failed": True,
                    "failure_reason": "rate_limit",
                    "final_response": "",
                },
            )
            q_code = None
            try:
                cli._run_single_query_mode(
                    stub, "work kanban task t_preflight", None, False, True,
                )
            except SystemExit as exc:
                q_code = exc.code

            auth_result = {
                "failed": True,
                "failure_reason": "auth",
                "final_response": "",
                "completed": False,
            }
            code78 = cli._single_query_exit_code(auth_result)
            allowed78 = cli._kanban_goal_loop_allowed(auth_result)

            report.update({
                "code75": code75,
                "allowed75": allowed75,
                "q_code": q_code,
                "code78": code78,
                "allowed78": allowed78,
                "judges": judges,
                "loops": len(loops),
                "expect75": KANBAN_RATE_LIMIT_EXIT_CODE,
                "expect78": KANBAN_TERMINAL_PROVIDER_EXIT_CODE,
            })
            print(json.dumps(report))
            ok = (
                code75 == KANBAN_RATE_LIMIT_EXIT_CODE
                and allowed75 is False
                and q_code == KANBAN_RATE_LIMIT_EXIT_CODE
                and loops == []
                and judges == []
                and code78 == KANBAN_TERMINAL_PROVIDER_EXIT_CODE
                and allowed78 is False
                and os.getcwd() == os.environ["HOSTILE_WS"]
            )
            raise SystemExit(0 if ok else 3)
            """
        ).lstrip(),
        encoding="utf-8",
    )

    argv = kbd._module_hermes_argv()
    prefix = _isolation_prefix(argv)
    probe_src = probe_path.read_text(encoding="utf-8")

    mutant = _run([sys.executable, "-c", probe_src], cwd=ws, env=env, timeout=120)
    assert mutant.returncode == 2, mutant.stdout + mutant.stderr
    mutant_report = json.loads(mutant.stdout.splitlines()[-1])
    assert mutant_report["hostile_flag"] is True or mutant_report["from_cwd"] is True
    assert mutant_report["has_stamp"] is False

    native = _run([*prefix, "-c", probe_src], cwd=ws, env=env, timeout=120)
    assert native.returncode == 0, native.stdout + native.stderr
    report = json.loads(native.stdout.splitlines()[-1])
    assert report["from_cwd"] is False
    assert report["has_stamp"] is True
    assert report["cwd"] == str(ws)
    assert report["q_code"] == 75
    assert report["code75"] == 75
    assert report["code78"] == 78
    assert report["loops"] == 0
    assert report["judges"] == []


def test_default_spawn_keeps_workspace_context_and_isolation_is_argv_not_env(monkeypatch, tmp_path):
    """cwd/TERMINAL_CWD/board/run/profile stay on the workspace; isolation is ``-P``."""
    from agent.delegation_context import DELEGATED_CHILD_ENV_MARKER
    from hermes_cli import kanban_db as kb
    from hermes_cli import kanban_db_dispatch as kbd

    root = tmp_path / ".hermes"
    profile = root / "profiles" / "w"
    profile.mkdir(parents=True)
    (profile / "config.yaml").write_text("toolsets:\n  - kanban\n", encoding="utf-8")
    (root / "config.yaml").write_text("toolsets:\n  - kanban\n", encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(root))
    monkeypatch.setenv(DELEGATED_CHILD_ENV_MARKER, "should-not-leak")
    monkeypatch.delenv("HERMES_BIN", raising=False)

    workspace = tmp_path / "ws"
    workspace.mkdir()

    captured: dict = {}

    class FakeProc:
        pid = 4242

    def fake_popen(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        captured["env"] = dict(kwargs.get("env") or {})
        captured["cwd"] = kwargs.get("cwd")
        return FakeProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    task = kb.Task(
        id="t_cwd_shadow",
        title="cwd pin",
        body=None,
        assignee="w",
        status="running",
        priority=0,
        created_by="test",
        created_at=1,
        started_at=None,
        completed_at=None,
        workspace_kind="dir",
        workspace_path=None,
        claim_lock="lock",
        claim_expires=None,
        tenant=None,
        current_run_id=9,
        model_override="grok-4.6",
        provider_override="xai-oauth",
    )
    assert kbd._default_spawn(task, str(workspace)) == 4242

    cmd = captured["cmd"]
    env = captured["env"]
    assert captured["cwd"] == str(workspace)
    assert "-P" in cmd
    assert "hermes_cli.main" in cmd
    assert cmd[cmd.index("-P") - 1] == sys.executable
    assert env.get("PYTHONSAFEPATH") == os.environ.get("PYTHONSAFEPATH")
    assert DELEGATED_CHILD_ENV_MARKER not in env
    assert env["HERMES_KANBAN_TASK"] == "t_cwd_shadow"
    assert env["HERMES_KANBAN_WORKSPACE"] == str(workspace)
    assert env["TERMINAL_CWD"] == str(workspace)
    assert env["HERMES_KANBAN_RUN_ID"] == "9"
    assert env["HERMES_PROFILE"] == "w"
    assert env["HERMES_KANBAN_BOARD"]
    assert env["HERMES_KANBAN_DB"]
    assert "-m" in cmd and "grok-4.6" in cmd
    assert "--provider" in cmd and "xai-oauth" in cmd


def test_gateway_module_argv_matches_dispatcher(monkeypatch):
    """Sibling surfaces must share the isolated module argv (no PATH-first drift)."""
    import shutil

    from gateway.run import _resolve_hermes_bin
    from hermes_cli import kanban_db_dispatch as kbd
    from hermes_cli._startup_fast import hermes_module_argv

    monkeypatch.delenv("HERMES_BIN", raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: "/tmp/planted/hermes")
    monkeypatch.setattr(kbd, "_safe_which_no_cwd", lambda name: "/tmp/planted/hermes")

    expected = [sys.executable, "-P", "-m", "hermes_cli.main"]
    assert hermes_module_argv() == expected
    assert kbd._module_hermes_argv() == expected
    assert kbd._resolve_hermes_argv() == expected
    assert _resolve_hermes_bin() == expected
