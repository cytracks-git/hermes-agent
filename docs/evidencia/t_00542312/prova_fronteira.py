"""Controle negativo ponta-a-ponta do DoD item 3 (t_00542312).

Grava o MESMO corpo longo (com o marcador terminal real medido no board atlas)
em dois bancos SQLite reais, e mede o que chegou ao disco:

  ANTES  = pin 587e13cbf9, sem a fronteira de admissao -> o corpo truncado PERSISTE
  DEPOIS = com a fronteira                             -> a escrita e RECUSADA

Roda em container, uid nao-root. Nenhuma alegacao: so o que o SELECT devolveu.
"""
import sys, pathlib, sqlite3

sys.path.insert(0, "/w")
from hermes_cli import kanban_db, kanban_db_connect

MARCADOR = (
    "⟪HERMES-CONTEXT-COMPRESSION: 5,455 of 5,655 chars omitted here by Hermes's "
    "context compressor. This is NOT part of the original tool call and must never "
    "be reproduced in new output — always write full, untruncated content.⟫"
)
# O head real medido em t_c505c2cc (176 chars), com o marcador colado no fim.
HEAD = ("## O defeito\n\nO repositório tem **98 worktrees**, e **92 deles** apontam para "
        "branch que não existe mais no remoto. O `atlas.local` monta um desses branches há 3 dias, ent")
CORPO_TRUNCADO = HEAD + MARCADOR
CORPO_INTEIRO = "## Especificação completa\n\n" + ("Conteúdo real e íntegro do card. " * 180)

modo = sys.argv[1]
db = pathlib.Path(f"/tmp/prova-{modo}.db")
db.unlink(missing_ok=True)
conn = kanban_db_connect.connect(db)

print(f"=== {modo.upper()} — fronteira de admissao presente? "
      f"{hasattr(kanban_db, 'validate_task_body')} ===")

# --- NEGATIVO: entrada sabotada (corpo truncado) ---
print(f"\n[NEGATIVO] tentando gravar corpo truncado ({len(CORPO_TRUNCADO)} chars, "
      f"head {len(HEAD)} + marcador)")
try:
    tid = kanban_db.create_task(conn, title="card sabotado", body=CORPO_TRUNCADO,
                                assignee="executor")
    gravado = conn.execute("SELECT body FROM tasks WHERE id=?", (tid,)).fetchone()[0]
    print(f"  ESCRITA PASSOU -> banco tem {len(gravado)} chars")
    print(f"  termina em marcador? {gravado.rstrip().endswith('⟫')}")
    print(f"  RESULTADO: DADO DESTRUIDO NO DISCO ({len(CORPO_TRUNCADO)-len(HEAD)} chars "
          f"de marcador no lugar da spec)")
except ValueError as e:
    print(f"  ESCRITA RECUSADA -> ValueError: {str(e)[:90]}...")
    n = conn.execute("SELECT count(*) FROM tasks").fetchone()[0]
    print(f"  linhas em tasks apos a recusa: {n}")
    print(f"  RESULTADO: NADA PERSISTIDO (o texto original segue vivo na origem)")

# --- POSITIVO: corpo longo legitimo tem de passar inteiro ---
print(f"\n[POSITIVO] gravando corpo longo integro ({len(CORPO_INTEIRO)} chars)")
tid2 = kanban_db.create_task(conn, title="card legitimo", body=CORPO_INTEIRO,
                             assignee="executor")
g2 = conn.execute("SELECT body FROM tasks WHERE id=?", (tid2,)).fetchone()[0]
print(f"  banco tem {len(g2)} chars | integro (byte a byte)? {g2 == CORPO_INTEIRO}")
print(f"  RESULTADO: {'PASSA INTEIRO' if g2 == CORPO_INTEIRO else 'CORROMPIDO'}")

# --- POSITIVO 2: comentario longo (12 dos 15 registros danificados eram comentarios) ---
print(f"\n[POSITIVO-COMENTARIO] gravando comentario longo ({len(CORPO_INTEIRO)} chars)")
kanban_db.add_comment(conn, tid2, "executor", CORPO_INTEIRO)
g3 = conn.execute("SELECT body FROM task_comments").fetchone()[0]
print(f"  banco tem {len(g3)} chars | integro? {g3 == CORPO_INTEIRO.strip()}")

print(f"\n[NEGATIVO-COMENTARIO] tentando gravar comentario truncado")
try:
    kanban_db.add_comment(conn, tid2, "executor", CORPO_TRUNCADO)
    n = conn.execute("SELECT count(*) FROM task_comments").fetchone()[0]
    print(f"  ESCRITA PASSOU -> task_comments agora tem {n} linhas (uma delas truncada)")
except ValueError as e:
    n = conn.execute("SELECT count(*) FROM task_comments").fetchone()[0]
    print(f"  ESCRITA RECUSADA -> ValueError; task_comments continua com {n} linha(s)")
