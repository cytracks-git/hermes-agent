"""Origem do lançamento: UI humana não nasce como delegated-child.

O Desktop/backend aberto para o operador não herda HERMES_DELEGATED_CHILD_CONTEXT
nem HERMES_KANBAN_TASK do worker que o disparou. O processo pai permanece
cercado (não há autopromoção). ``hermes serve`` no mesmo processo do worker
continua restrito (aviso + 403). ``--build-only`` não abre interface.

Os testes exercitam ``cmd_gui``/``start_server`` reais: só o processo Electron
e o servidor uvicorn são substituídos, nunca o predicado de identidade.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.delegation_context import DELEGATED_CHILD_ENV_MARKER, KANBAN_ENV_KEYS
from hermes_cli import main as cli_main
from hermes_cli import main_desktop
from hermes_cli.interactive_launch_context import KANBAN_RESTRICTED_LAUNCH_MESSAGE


@pytest.fixture(autouse=True)
def _isolate_xdg_data_home(tmp_path, monkeypatch):
    """`cmd_gui` registra um .desktop sob XDG_DATA_HOME; manter fora do HOME real."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg-data"))
    monkeypatch.setenv("GNOME_KEYRING_CONTROL", str(tmp_path / "keyring"))


@pytest.fixture
def fenced_home(tmp_path, monkeypatch):
    """HERMES_HOME real e marcador de descendente apontando para a MESMA raiz."""
    home = tmp_path / ".hermes"
    (home / "kanban").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_HOME", str(home))
    monkeypatch.delenv(DELEGATED_CHILD_ENV_MARKER, raising=False)
    return home


def _ns(**kw):
    defaults = dict(
        skip_build=False, build_only=False, force_build=False, source=False,
        fake_boot=False, ignore_existing=False, hermes_root=None, cwd=None,
        setup_tcc_identity=False, identity=None,
    )
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def _desktop_tree(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "hermes-agent"
    desktop_dir = root / "apps" / "desktop"
    desktop_dir.mkdir(parents=True)
    (desktop_dir / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli_main, "PROJECT_ROOT", root)
    if sys.platform == "darwin":
        exe = desktop_dir / "release" / "mac-arm64" / "Hermes.app" / "Contents" / "MacOS" / "Hermes"
    elif sys.platform == "win32":
        exe = desktop_dir / "release" / "win-unpacked" / "Hermes.exe"
    else:
        exe = desktop_dir / "release" / "linux-unpacked" / "hermes"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("", encoding="utf-8")
    if sys.platform not in ("darwin", "win32"):
        (exe.parent / "chrome-sandbox").write_text("", encoding="utf-8")
    return exe


_WORKER_IDENTITY_KEYS = (DELEGATED_CHILD_ENV_MARKER, *KANBAN_ENV_KEYS)


def _assert_human_spawn_env(spawn_env: dict) -> None:
    leaked = [key for key in _WORKER_IDENTITY_KEYS if key in spawn_env]
    assert leaked == [], leaked


@pytest.mark.parametrize("restricted", [True, False])
def test_desktop_spawn_is_human_even_when_parent_is_fenced(
    tmp_path, monkeypatch, capsys, fenced_home, restricted
):
    """Controle positivo E negativo no mesmo estímulo.

    Pai cercado: Electron abre, o env do FILHO não carrega o marcador, o pai
    continua cercado, e a UI não é anunciada como read-only (ela não é).
    Pai limpo: o mesmo caminho abre sem aviso — o sensor não acusa todo mundo.
    """
    exe = _desktop_tree(tmp_path, monkeypatch)
    if restricted:
        monkeypatch.setenv(DELEGATED_CHILD_ENV_MARKER, str(fenced_home))
        monkeypatch.setenv("HERMES_KANBAN_TASK", "t_worker")
        monkeypatch.setenv("HERMES_KANBAN_RUN_ID", "99")

    launch_ok = subprocess.CompletedProcess([str(exe)], 0)
    with patch("hermes_cli.main_desktop._desktop_build_needed", return_value=False), \
         patch("hermes_cli.main_install_repair._resolve_node_runtime_npm", return_value="/usr/bin/npm"), \
         patch("hermes_cli.main_desktop._desktop_linux_sandbox_fixup", return_value=True), \
         patch("hermes_cli.main_desktop._register_linux_desktop_entry", return_value=None), \
         patch("hermes_cli.main_desktop.subprocess.run", return_value=launch_ok) as run, \
         pytest.raises(SystemExit) as exc:
        cli_main.cmd_gui(_ns())

    assert exc.value.code == 0
    assert run.call_count == 1, "o app tem de abrir nos dois casos"
    assert str(exe) in run.call_args.args[0][0]
    spawn_env = run.call_args.kwargs["env"]
    _assert_human_spawn_env(spawn_env)
    assert spawn_env.get("HERMES_HOME") == os.environ["HERMES_HOME"]
    err = capsys.readouterr().err
    assert KANBAN_RESTRICTED_LAUNCH_MESSAGE not in err, err
    if restricted:
        assert os.environ[DELEGATED_CHILD_ENV_MARKER] == str(fenced_home)
        assert os.environ["HERMES_KANBAN_TASK"] == "t_worker"


def test_desktop_launch_env_strips_worker_identity_for_profile_home(
    tmp_path, monkeypatch, fenced_home
):
    """Perfil no HERMES_HOME não é identidade de worker: a UI do perfil nasce humana."""
    profile = fenced_home / "profiles" / "writer"
    profile.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(profile))
    monkeypatch.setenv(DELEGATED_CHILD_ENV_MARKER, str(fenced_home))
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_worker")
    monkeypatch.setattr(main_desktop, "_desktop_launch_options", lambda: ([], "auto", "auto", "auto"))
    monkeypatch.setattr(main_desktop, "_detect_linux_password_store", lambda: None)

    env, _flags = main_desktop._desktop_launch_env(_ns(cwd=str(tmp_path)))

    _assert_human_spawn_env(env)
    assert env["HERMES_HOME"] == str(profile)
    assert os.environ[DELEGATED_CHILD_ENV_MARKER] == str(fenced_home)
    assert os.environ["HERMES_KANBAN_TASK"] == "t_worker"


def test_build_only_opens_no_ui_and_emits_no_launch_notice(
    tmp_path, monkeypatch, capsys, fenced_home
):
    """`--build-only` produz artefato e retorna: nenhum processo de UI, nenhum aviso."""
    exe = _desktop_tree(tmp_path, monkeypatch)
    monkeypatch.setenv(DELEGATED_CHILD_ENV_MARKER, str(fenced_home))

    with patch("hermes_cli.main_desktop._desktop_build_needed", return_value=False), \
         patch("hermes_cli.main_install_repair._resolve_node_runtime_npm", return_value="/usr/bin/npm"), \
         patch("hermes_cli.main_desktop._desktop_linux_sandbox_fixup", return_value=True), \
         patch("hermes_cli.main_desktop._register_linux_desktop_entry", return_value=None), \
         patch("hermes_cli.main_desktop.subprocess.run", side_effect=AssertionError("--build-only lançou UI")):
        cli_main.cmd_gui(_ns(build_only=True))

    captured = capsys.readouterr()
    assert str(exe) in captured.out
    assert "not launching; --build-only" in captured.out
    assert KANBAN_RESTRICTED_LAUNCH_MESSAGE not in captured.err


class _StopBeforeBind(Exception):
    """Sentinela: o primeiro efeito de start_server depois do aviso."""


@pytest.mark.parametrize("restricted", [True, False])
def test_backend_start_server_warns_before_any_bind_side_effect(
    monkeypatch, capsys, fenced_home, restricted
):
    """O backend (`serve`/`dashboard`/app direto) carrega a identidade do PROCESSO.

    O primeiro efeito real de ``start_server`` é substituído por um sentinela, de
    modo que nenhum socket abre: se o aviso chegou ao stderr, ele saiu ANTES de
    qualquer efeito de bind. O predicado de identidade é o de produção.
    """
    from hermes_cli import web_server

    if restricted:
        monkeypatch.setenv(DELEGATED_CHILD_ENV_MARKER, str(fenced_home))

    def stop(*_a, **_k):
        raise _StopBeforeBind

    monkeypatch.setattr(web_server, "_apply_ssh_session_token", stop)

    with pytest.raises(_StopBeforeBind):
        web_server.start_server(host="127.0.0.1", port=0, open_browser=False)

    err = capsys.readouterr().err
    assert (KANBAN_RESTRICTED_LAUNCH_MESSAGE in err) is restricted, err
