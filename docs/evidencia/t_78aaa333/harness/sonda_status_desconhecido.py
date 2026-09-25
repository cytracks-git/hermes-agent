"""O codigo INSTALADO sabe lidar com um card em ``waiting_approval``?

Por que existe
--------------
Medido nesta rodada: o board de producao ``~/.hermes/kanban/boards/atlas`` ja
tem o esquema do patch (tabela ``approval_requests``, indices), porque os
workers rodam com o WORKTREE em ``sys.path[0]``. O gateway, o dispatcher e o
Desktop, porem, carregam a INSTALACAO (``~/.hermes/hermes-agent``, d7ea741),
cujo ``VALID_STATUSES`` nao contem ``waiting_approval``. Um lado do contrato
existe e o outro nunca soube: a classe ORFAO.

Esta sonda mede o efeito REAL disso num banco DESCARTAVEL, com os dois modulos
carregados da arvore que se quer medir (``--arvore``), sem tocar producao:

1. um card parado em ``waiting_approval`` aparece para o dispatcher?
2. ``recompute_ready`` / promocao o alcancam ou o deixam para tras?
3. filho com esse pai promove indevidamente?

O controle POSITIVO obrigatorio e o mesmo estimulo sobre um card ``blocked``:
se ``blocked`` tambem sumisse, a sonda estaria medindo a propria consulta, nao
o status desconhecido.

Uso: python3 sonda_status_desconhecido.py            (usa a arvore no sys.path)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect

STATUS_NOVO = "waiting_approval"


def _forca_status(conn, task_id: str, status: str) -> None:
    """Grava o status DIRETO, sem passar pela validacao do modulo carregado.

    Proposital: o objetivo e simular o banco que o OUTRO lado (worktree) ja
    produziu, e perguntar o que ESTE codigo faz ao encontra-lo. Passar pela API
    validadora mediria a validacao, nao a convivencia.
    """
    conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))
    conn.commit()


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    conn = connect(kb.init_db(db_path=tmp / "orfao.db"))

    saida: dict = {
        "modulo_kanban_db": kb.__file__,
        "status_conhecidos": sorted(getattr(kb, "VALID_STATUSES", [])),
        "conhece_waiting_approval": STATUS_NOVO in getattr(kb, "VALID_STATUSES", set()),
    }

    # Alvo: card parado no status novo. Controle positivo: card em ``blocked``,
    # status que ESTE codigo conhece, com o mesmo estimulo.
    alvo = kb.create_task(conn, title="alvo status novo", assignee="sonda")
    controle = kb.create_task(conn, title="controle blocked", assignee="sonda")
    filho = kb.create_task(conn, title="filho do alvo", assignee="sonda", parents=[alvo])
    _forca_status(conn, alvo, STATUS_NOVO)
    _forca_status(conn, controle, "blocked")

    kb.recompute_ready(conn)

    def _status(tid: str) -> str:
        row = conn.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()
        return row["status"] if row else "<sumiu>"

    saida["depois_de_recompute"] = {
        "alvo": _status(alvo),
        "controle_blocked": _status(controle),
        "filho": _status(filho),
    }

    # O filho NAO pode promover: o pai nao terminou. Se promover, o codigo
    # antigo trata status desconhecido como "nao bloqueante" e libera trabalho
    # dependente cedo demais -- o dano concreto do orfao.
    saida["filho_promoveu_indevidamente"] = _status(filho) in {"ready", "running"}

    # O card parado aparece nas listagens que o operador e o dispatcher usam?
    try:
        listadas = [t.id for t in kb.list_tasks(conn)]
        saida["list_tasks_sem_filtro"] = {
            "alvo_aparece": alvo in listadas,
            "controle_aparece": controle in listadas,
            "total": len(listadas),
        }
    except Exception as exc:
        saida["list_tasks_sem_filtro"] = {"erro": repr(exc)}

    # Filtrar POR esse status: o codigo antigo recusa o proprio valor que o
    # banco ja contem, entao o operador nao consegue nem listar o que travou.
    try:
        listadas = [t.id for t in kb.list_tasks(conn, status=STATUS_NOVO)]
        saida["list_tasks_filtro_status_novo"] = {"ids": listadas}
    except Exception as exc:
        saida["list_tasks_filtro_status_novo"] = {"erro": repr(exc)}

    # O dispatcher: ele enxerga o card parado como trabalho pendente?
    try:
        from hermes_cli import kanban_db_dispatch as disp

        pendentes = [t.id for t in kb.list_tasks(conn, status="ready")]
        saida["dispatch"] = {
            "modulo": disp.__file__,
            "ready_ids": pendentes,
            "alvo_em_ready": alvo in pendentes,
        }
    except Exception as exc:
        saida["dispatch"] = {"erro": repr(exc)}

    # A retomada existe neste codigo? Sem ela, um card parado nunca volta.
    saida["tem_resume_de_aprovacao"] = all(
        hasattr(kb, nome) for nome in ("pause_for_approval", "resume_from_pause")
    )

    conn.close()
    print(json.dumps(saida, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("HERMES_KANBAN_DB", "")
    raise SystemExit(main())
