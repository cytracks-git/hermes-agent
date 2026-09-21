"""Identidade de lançamento: UI humana não nasce cercada; descendente continua cercado."""

from __future__ import annotations

from typing import Mapping

KANBAN_RESTRICTED_LAUNCH_MESSAGE = (
    "Kanban is read-only for this launch: the backend inherited an agent's delegated-worker restrictions. "
    "Reading the board is still available. To make changes, wait for active work to finish, "
    "then quit this Desktop/backend and reopen Hermes from the operating system or a normal user terminal, "
    "not from an agent tool. Refreshing the page or switching profiles does not change the launch identity."
)


def human_interactive_subprocess_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Env do filho Desktop/backend humano. Não muta o processo chamador.

    Identidade de worker/delegate é do PROCESSO. Copiá-la para o Electron (e dali
    para o ``hermes serve`` que ele sobe) fazia a UI do operador nascer como
    delegated-child. Descendentes continuam cercados por
    ``delegated_child_subprocess_env``; esta é a inversa na fronteira da
    superfície humana. Tirar o marcador *aqui* não autopromove o agente.
    """
    import os

    from agent.delegation_context import DELEGATED_CHILD_ENV_MARKER, KANBAN_ENV_KEYS

    source = os.environ if env is None else env
    drop = {DELEGATED_CHILD_ENV_MARKER, *KANBAN_ENV_KEYS}
    return {k: v for k, v in source.items() if k not in drop}


def kanban_launch_restriction(board: str | None = None) -> str | None:
    from agent.delegation_context import kanban_path_is_fenced
    from hermes_cli.kanban_db import kanban_db_path, kanban_home

    if kanban_path_is_fenced(kanban_home()) or kanban_path_is_fenced(kanban_db_path(board=board)):
        return KANBAN_RESTRICTED_LAUNCH_MESSAGE
    return None


def warn_restricted_launch() -> None:
    import sys

    if reason := kanban_launch_restriction():
        print(reason, file=sys.stderr, flush=True)
