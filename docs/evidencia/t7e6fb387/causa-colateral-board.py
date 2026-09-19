"""Causa raiz do colateral no board de producao, medida — nao inferida.

Hipotese: `HERMES_KANBAN_DB` tem precedencia sobre `HERMES_HOME` na resolucao do
caminho do banco. O harness standalone so seta `HERMES_HOME` (e monkeypatcha
`Path.home`), entao `create_task` foi parar no atlas de PRODUCAO.

Este script NAO escreve em banco nenhum: so pergunta qual caminho seria usado.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/Users/farantes/atlas/wt/t7e6fb387-direto")

falso_home = Path(tempfile.mkdtemp(prefix="causa-t7e-")) / ".hermes"
falso_home.mkdir(parents=True)

print("=" * 72)
print("PERGUNTA: com HERMES_HOME isolado, para ONDE o kanban escreve?")
print("=" * 72)

# --- Cenario A: exatamente o que o harness standalone faz -------------------
os.environ["HERMES_HOME"] = str(falso_home)
print(f"\n[A] harness standalone (so seta HERMES_HOME)")
print(f"    HERMES_HOME      = {os.environ.get('HERMES_HOME')}")
print(f"    HERMES_KANBAN_DB = {os.environ.get('HERMES_KANBAN_DB')}")

from hermes_cli import kanban_db as kb  # noqa: E402

destino_a = kb.kanban_db_path()
print(f"    -> kanban_db_path() = {destino_a}")
producao = Path.home() / ".hermes/kanban/boards/atlas/kanban.db"
print(f"    -> E O BANCO DE PRODUCAO? {Path(destino_a).resolve() == producao.resolve()}")

# --- Cenario B: o que o conftest do pytest faz ------------------------------
print(f"\n[B] pytest (conftest limpa os pins de kanban)")
for var in ("HERMES_KANBAN_DB", "HERMES_KANBAN_BOARD", "HERMES_KANBAN_HOME",
            "HERMES_KANBAN_WORKSPACES_ROOT"):
    os.environ.pop(var, None)
destino_b = kb.kanban_db_path()
print(f"    -> kanban_db_path() = {destino_b}")
print(f"    -> E O BANCO DE PRODUCAO? {Path(destino_b).resolve() == producao.resolve()}")
print(f"    -> esta sob o HERMES_HOME isolado? {Path(destino_b).is_relative_to(falso_home)}")

print()
print("=" * 72)
print("VEREDITO")
print("=" * 72)
if Path(destino_a).resolve() == producao.resolve() and Path(destino_b).is_relative_to(falso_home):
    print("CONFIRMADO: HERMES_KANBAN_DB (injetado no worker) vence HERMES_HOME.")
    print("  - harness standalone -> escreveu no board de PRODUCAO")
    print("  - suite pytest       -> isolada pelo conftest, NAO tocou producao")
else:
    print("HIPOTESE NAO CONFIRMADA — medir de novo antes de afirmar qualquer coisa.")
