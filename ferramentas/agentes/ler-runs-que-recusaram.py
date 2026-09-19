#!/usr/bin/env python3
"""Mostra o texto REAL com que os runs de revisao morreram, sem parafrase."""
import os, sqlite3, sys, textwrap

alvo = sys.argv[1] if len(sys.argv) > 1 else "t_ad873a37"
conn = sqlite3.connect(f"file:{os.environ['HERMES_KANBAN_DB']}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

for r in conn.execute(
    "SELECT id, profile, status, outcome, summary, error, metadata FROM task_runs "
    "WHERE task_id=? AND outcome='crashed' ORDER BY id", (alvo,)):
    print("=" * 72)
    print(f"run {r['id']}  profile={r['profile']}  outcome={r['outcome']}")
    for campo in ("summary", "error", "metadata"):
        v = r[campo]
        if v:
            print(f"-- {campo} --")
            print(textwrap.indent(str(v)[:2500], "   "))
print("=" * 72)
print("== comentarios que citam claim_lock / autoria ==")
for c in conn.execute(
    "SELECT author, body, created_at FROM task_comments WHERE task_id=? ORDER BY id", (alvo,)):
    corpo = c["body"] or ""
    if any(k in corpo.lower() for k in ("claim_lock", "claim lock", "autoria", "mesmo processo",
                                        "proprio", "próprio", "self-review", "own work")):
        print(f"\n--- {c['author']} ---")
        print(textwrap.indent(corpo[:2000], "   "))
