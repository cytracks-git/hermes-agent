"""Diagnóstico de identidade herdada; nunca promove um descendente a operador."""

KANBAN_RESTRICTED_LAUNCH_MESSAGE = (
    "Kanban is read-only for this launch: the backend inherited an agent's delegated-worker restrictions. "
    "Reading the board is still available. To make changes, wait for active work to finish, "
    "then quit this Desktop/backend and reopen Hermes from the operating system or a normal user terminal, "
    "not from an agent tool. Refreshing the page or switching profiles does not change the launch identity."
)


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
