#!/usr/bin/env python3
"""Exercita `authorship_identity` contra o BOARD REAL, nao contra fixture.

Teste verde em banco de laboratorio nao prova que o sinal responde certo sobre
o card que de fato queimou quatro runs. Aqui o alvo e o `t_ad873a37` real.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from hermes_cli import kanban_db as kb          # noqa: E402
from hermes_cli import kanban_db_connect as kbc  # noqa: E402

alvos = sys.argv[1:] or ["t_ad873a37"]
with kbc.connect() as conn:
    for tid in alvos:
        print(f"=== {tid} ===")
        print(json.dumps(kb.authorship_identity(conn, tid), indent=2, ensure_ascii=False))
        print()
    meu = os.environ.get("HERMES_KANBAN_TASK")
    if meu:
        print(f"=== {meu} (este card, identificado pelo env do proprio worker) ===")
        print(json.dumps(kb.authorship_identity(conn, meu), indent=2, ensure_ascii=False))
        print()
        print("--- trecho de Authorship que o worker LE no contexto ---")
        texto = kb.build_worker_context(conn, "t_ad873a37")
        bloco = texto.split("## Authorship", 1)
        print("## Authorship" + bloco[1].split("\n##", 1)[0] if len(bloco) > 1 else "(sem secao)")
