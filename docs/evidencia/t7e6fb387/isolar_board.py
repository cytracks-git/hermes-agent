"""Isolamento de board para provas que rodam DENTRO de uma sessao worker.

Existe por um defeito MEDIDO, nao por precaucao teorica. O harness da rodada 2
setava apenas ``HERMES_HOME`` e criou 10 cards `assignee=worker` no board atlas
de PRODUCAO. Custo medido pelo orquestrador: as 03:40:05 o teto global de 4
slots estava consumido por 3 fixtures (`t_a20e6f81`, `t_e3fc3130`,
`t_82e38add`), com 23 cards reais parados em `ready`; liberados os claims, o
dispatcher admitiu dois cards reais no mesmo tick.

Causa raiz (``docs/evidencia/t7e6fb387/causa-colateral-board.py``):

    [A] so HERMES_HOME  -> kanban_db_path() = ~/.hermes/kanban/boards/atlas/kanban.db
    [B] pins limpos     -> kanban_db_path() = <tmp>/.hermes/kanban.db

``HERMES_KANBAN_DB`` e injetado em todo worker e VENCE ``HERMES_HOME``. Setar
so o segundo nao isola nada. A suite pytest nunca teve esse furo — o
``tests/conftest.py`` ja limpa esses pins; o furo era dos scripts avulsos.

Uso, ANTES de qualquer ``import hermes_cli.kanban_db``::

    from isolar_board import isolar_board
    HOME = isolar_board("minha-prova-")
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Pins que apontam um worker para o board de producao. Mesma lista que o
# tests/conftest.py limpa, mais os marcadores de contexto filho que fazem o
# kernel recusar a escrita ("delegate_task child contexts cannot mutate").
_PINS_DE_BOARD = (
    "HERMES_KANBAN_DB",
    "HERMES_KANBAN_BOARD",
    "HERMES_KANBAN_HOME",
    "HERMES_KANBAN_WORKSPACES_ROOT",
    "HERMES_KANBAN_LOGS_ROOT",
    "HERMES_KANBAN_TASK",
    "HERMES_KANBAN_WORKSPACE",
    "HERMES_KANBAN_RUN_ID",
    "HERMES_KANBAN_CLAIM_LOCK",
    "HERMES_DELEGATED_CHILD_CONTEXT",
    "HERMES_SUPERVISED_CHILD",
)


def isolar_board(prefixo: str = "prova-kanban-") -> Path:
    """Aponta o kanban para um HERMES_HOME descartavel e devolve a raiz.

    Levanta ``RuntimeError`` se o isolamento nao puder ser provado: falhar alto
    e melhor que escrever no board de producao, que foi o defeito original.
    """
    raiz = Path(tempfile.mkdtemp(prefix=prefixo))
    home = raiz / ".hermes"
    home.mkdir(parents=True, exist_ok=True)

    for var in _PINS_DE_BOARD:
        os.environ.pop(var, None)
    os.environ["HERMES_HOME"] = str(home)

    from hermes_cli import kanban_db as kb

    kb._INITIALIZED_PATHS.clear()
    destino = Path(kb.kanban_db_path())
    if not destino.is_relative_to(home):
        raise RuntimeError(
            f"isolamento FALHOU: kanban_db_path()={destino} esta fora de {home}. "
            f"Abortando antes de tocar num board real."
        )
    return raiz


def afirmar_isolado() -> Path:
    """Reconfere o isolamento no momento do uso e devolve o banco em vigor."""
    from hermes_cli import kanban_db as kb

    destino = Path(kb.kanban_db_path())
    home = Path(os.environ.get("HERMES_HOME", "")).expanduser()
    if not home or not destino.is_relative_to(home):
        raise RuntimeError(
            f"board NAO isolado: kanban_db_path()={destino}, HERMES_HOME={home}"
        )
    return destino
