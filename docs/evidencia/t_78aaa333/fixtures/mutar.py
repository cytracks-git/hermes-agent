#!/usr/bin/env python3
"""Mutantes do contrato v2 (t_069cfdac). Aplicados numa CÓPIA da fonte, nunca na árvore real.

Uso: python3 mutar.py <raiz-da-copia> <n>

Cada mutante quebra exatamente uma guarda que o contrato exige; o teste
correspondente tem de FALHAR (mutante morto). Um mutante que sobrevive é
fixture fraca, não código seguro.
"""
import pathlib
import sys

RAIZ = pathlib.Path(sys.argv[1])
N = sys.argv[2]


def troca(rel, velho, novo, conta=1):
    p = RAIZ / rel
    txt = p.read_text()
    assert txt.count(velho) >= conta, f"âncora não encontrada em {rel}: {velho[:60]!r}"
    p.write_text(txt.replace(velho, novo, conta))
    print(f"mutado {rel}")


if N == "1":
    # M1 — recompute_ready passa a varrer E promover waiting_approval (contrato E-5).
    # As DUAS camadas: o SELECT (SQL, aspas simples) e a guarda do UPDATE do ramo 'todo'.
    troca("hermes_cli/kanban_db.py",
          "\"FROM tasks WHERE status IN ('todo', 'blocked')\"",
          "\"FROM tasks WHERE status IN ('todo', 'blocked', 'waiting_approval')\"")
    troca("hermes_cli/kanban_db.py",
          "\"UPDATE tasks SET status = ? WHERE id = ? AND status = 'todo'\",",
          "\"UPDATE tasks SET status = ? WHERE id = ? AND status IN ('todo','waiting_approval')\",")

elif N == "2":
    # M2 — o portão protegido passa a honrar yolo (contrato A-3 / C-26).
    troca("tools/file_tools_write_guards.py",
          "    targets = \", \".join(dict.fromkeys(reasons))",
          "    from tools.approval import is_session_yolo_enabled as _y\n"
          "    from tools.approval_context import get_current_session_key as _k\n"
          "    if _y(_k()):\n"
          "        return None\n"
          "    targets = \", \".join(dict.fromkeys(reasons))")

elif N == "3":
    # M3 — o PATCH genérico do dashboard ganha o verbo 'approve' (contrato A-3 / C-24).
    # Era o mutante NÃO MEDIDO em v1, por falta de fastapi no lab.
    troca("plugins/kanban/dashboard/plugin_api.py",
          "    \"triage\": lambda conn, tid, p: _drag_to(conn, tid, \"triage\")}",
          "    \"triage\": lambda conn, tid, p: _drag_to(conn, tid, \"triage\"),\n"
          "    \"approve\": lambda conn, tid, p: _set_status_direct(conn, tid, \"ready\")}")

elif N == "4":
    # M4 — 'approval_requested' entra SÓ na lista do gateway, sem o espelho do TUI
    # (contrato U-4). O xfail estrito de C-35 tem de virar XPASS => falha do run.
    troca("gateway/kanban_watchers_notifier.py",
          "\"changes_requested\")", "\"changes_requested\", \"approval_requested\")")

else:
    sys.exit(f"mutante desconhecido: {N}")
