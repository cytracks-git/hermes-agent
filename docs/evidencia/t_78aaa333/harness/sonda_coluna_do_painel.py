"""Um card parado em ``waiting_approval`` cai em que COLUNA do painel?

Por que existe
--------------
``plugin_api.BOARD_COLUMNS`` comenta que "a status missing here gets
mis-bucketed into ``todo``". Comentario nao e medicao. Esta sonda pergunta ao
ROTEADOR REAL do painel (o mesmo ``/board`` que o dashboard e o plugin do
Desktop chamam) em que coluna o card aparece, nas duas arvores:

    ANTIGA = instalacao compartilhada, sem ``waiting_approval``
    NOVA   = worktree deste card, com a coluna propria

Controle positivo: um card ``blocked`` no mesmo banco. Se ele tambem fosse
parar em ``todo``, a sonda estaria medindo a propria montagem, nao o status
desconhecido.

Uso: python3 sonda_coluna_do_painel.py   (PYTHONPATH aponta para a arvore)
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli import kanban_db as kb
from hermes_cli.kanban_db_connect import connect

STATUS_NOVO = "waiting_approval"


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    db = kb.init_db(db_path=tmp / "painel.db")
    conn = connect(db)

    alvo = kb.create_task(conn, title="alvo esperando humano", assignee="sonda")
    controle = kb.create_task(conn, title="controle blocked", assignee="sonda")
    # Grava direto: o objetivo e o banco que o OUTRO lado ja produz, e perguntar
    # o que ESTE painel faz ao encontra-lo.
    conn.execute("UPDATE tasks SET status=? WHERE id=?", (STATUS_NOVO, alvo))
    conn.execute("UPDATE tasks SET status='blocked' WHERE id=?", (controle,))
    conn.commit()

    import contextlib

    import plugins.kanban.dashboard.plugin_api as api_mod

    @contextlib.contextmanager
    def _board(_slug=None):
        # Uma conexao por requisicao: o TestClient roda cada handler numa thread
        # do pool e conexao SQLite e presa a thread que a criou.
        fresh = connect(db)
        try:
            yield ("sonda", fresh)
        finally:
            fresh.close()

    api_mod._board_conn = _board
    app = FastAPI()
    app.include_router(api_mod.router)
    client = TestClient(app)

    corpo = client.get("/board").json()
    colunas = {c["name"]: [t["id"] for t in c["tasks"]] for c in corpo["columns"]}

    def _onde(tid: str) -> str:
        for nome, ids in colunas.items():
            if tid in ids:
                return nome
        return "<nenhuma coluna>"

    saida = {
        "modulo_painel": api_mod.__file__,
        "colunas_declaradas": list(colunas),
        "tem_coluna_propria": STATUS_NOVO in colunas,
        "alvo_caiu_em": _onde(alvo),
        "controle_blocked_caiu_em": _onde(controle),
    }
    saida["ALVO_NA_COLUNA_ERRADA"] = saida["alvo_caiu_em"] != STATUS_NOVO
    saida["controle_correto"] = saida["controle_blocked_caiu_em"] == "blocked"

    conn.close()
    print(json.dumps(saida, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
