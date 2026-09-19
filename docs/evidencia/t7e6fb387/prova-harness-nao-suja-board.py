"""Prova de que o harness corrigido NAO escreve mais no board de producao.

Conta os cards do board real antes e depois de rodar o harness inteiro.
CONTROLE POSITIVO embutido: o harness tem de continuar RODANDO (8 casos), nao
apenas parar de sujar. Um harness que nao roda tambem "nao suja".
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

BOARD = Path.home() / ".hermes/kanban/boards/atlas/kanban.db"
WT = Path("/Users/farantes/atlas/wt/t7e6fb387-direto")
HARNESS = WT / "docs/evidencia/t7e6fb387/harness-revisor-rodada2.py"


def censo() -> tuple[int, int, list[str]]:
    con = sqlite3.connect(f"file:{BOARD}?mode=ro", uri=True)
    try:
        total = con.execute("SELECT count(*) FROM tasks").fetchone()[0]
        worker = con.execute(
            "SELECT count(*) FROM tasks WHERE assignee='worker'").fetchone()[0]
        ids = [r[0] for r in con.execute(
            "SELECT id FROM tasks WHERE assignee='worker' ORDER BY id")]
        return total, worker, ids
    finally:
        con.close()


a_total, a_worker, a_ids = censo()
print(f"ANTES   total={a_total}  assignee=worker={a_worker}")

proc = subprocess.run(
    [sys.executable, str(HARNESS)], capture_output=True, text=True, cwd=str(WT))
saida = (proc.stdout + proc.stderr).strip().splitlines()
print(f"\n--- harness (rc={proc.returncode}) ---")
for linha in saida[-10:]:
    print(f"  {linha}")

d_total, d_worker, d_ids = censo()
print(f"\nDEPOIS  total={d_total}  assignee=worker={d_worker}")

novos = sorted(set(d_ids) - set(a_ids))
limpo = (a_total == d_total) and (a_worker == d_worker) and not novos
rodou = any("conformes:" in ln for ln in saida)

print("\n" + "=" * 68)
if novos:
    print(f"FALHOU: o harness criou {len(novos)} card(s) no board real: {novos}")
elif not rodou:
    print("INCONCLUSIVO: o harness nao chegou ao fim; 'nao sujou' nao prova nada.")
elif limpo:
    print("PROVA: o harness rodou ate o fim e o board de PRODUCAO nao mudou.")
    print(f"       delta total={d_total - a_total}  delta worker={d_worker - a_worker}")
print("=" * 68)
sys.exit(0 if (limpo and rodou) else 1)
