"""Os QUATRO controles que o card t_7e6fb387 exige, na ordem em que os pede.

  1. commit local, rama NAO empurrada        -> tem de RECUSAR (e dizer o que fazer)
  2. o MESMO card depois do `git push`       -> tem de FECHAR
  3. card de leitura pura, sem commit         -> tem de FECHAR (nao virar paranoia)
  4. metadata com SHA inventado               -> tem de RECUSAR

"Cole a saida real dos quatro. Sem isso nao esta provado."

O caso 2 usa o MESMO card do caso 1 de proposito: a unica variavel entre
recusar e fechar e o push. Se fossem cards diferentes, a comparacao nao provaria
que foi o push que mudou o veredito.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "/Users/farantes/atlas/wt/t7e6fb387-direto")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolar_board import isolar_board  # noqa: E402

RAIZ = isolar_board("quatro-controles-")

from hermes_cli import kanban_db as kb          # noqa: E402
from hermes_cli import kanban_db_connect as kbc  # noqa: E402

kb._INITIALIZED_PATHS.clear()
kb.init_db()


def git(*a, cwd=None):
    r = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"git {' '.join(a)}: {r.stderr}"
    return r.stdout


def repo_com_origin(d: Path):
    origin = d / "origin.git"
    git("init", "--bare", str(origin))
    proj = d / "project"
    git("clone", str(origin), str(proj))
    git("-C", str(proj), "config", "user.email", "t@example.com")
    git("-C", str(proj), "config", "user.name", "t")
    (proj / "README.md").write_text("hello\n")
    git("-C", str(proj), "add", "README.md")
    git("-C", str(proj), "commit", "-m", "init")
    git("-C", str(proj), "push", "origin", "HEAD")
    return proj


def claimed(conn, **cols):
    tid = kb.create_task(conn, title="t", assignee="worker")
    if cols:
        sets = ", ".join(f"{k}=?" for k in cols)
        with kb.write_txn(conn):
            conn.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*cols.values(), tid))
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
    assert kb.claim_task(conn, tid, claimer="worker") is not None
    return tid


def cabecalho(n, titulo, esperado):
    print()
    print("=" * 76)
    print(f"CONTROLE {n} — {titulo}")
    print(f"ESPERADO: {esperado}")
    print("=" * 76)


ok = []

with kbc.connect() as conn:
    # ---------------------------------------------------------------- 1 e 2
    d = RAIZ / "c12"; d.mkdir()
    proj = repo_com_origin(d)
    tid = claimed(conn, workspace_kind="dir", workspace_path=str(proj))
    git("-C", str(proj), "checkout", "-b", "trabalho-do-card")
    (proj / "novo.py").write_text("# entrega\n")
    git("-C", str(proj), "add", "novo.py")
    git("-C", str(proj), "commit", "-m", "trabalho do card")

    cabecalho(1, "commit local, rama NAO empurrada", "RECUSAR")
    try:
        kb.complete_task(conn, tid, summary="Implementei, testei, tudo passou.")
        print("  RESULTADO: FECHOU  <-- ERRADO")
    except kb.UnpushedWorkError as e:
        print(f"  RESULTADO: RECUSOU\n  mensagem ao worker:\n    {e}")
        print(f"  status do card: {kb.get_task(conn, tid).status}")
        ok.append(1)

    cabecalho(2, "O MESMO card, apos `git push` (unica variavel)", "FECHAR")
    git("-C", str(proj), "push", "-u", "origin", "trabalho-do-card")
    r = kb.complete_task(conn, tid, summary="empurrei")
    st = kb.get_task(conn, tid).status
    print(f"  RESULTADO: complete_task={r}  status={st}")
    if r and st == "done":
        ok.append(2)
    else:
        print("  <-- ERRADO")

    # ------------------------------------------------------------------- 3
    cabecalho(3, "card de leitura pura, nenhum commit", "FECHAR")
    leitura = RAIZ / "c3-leitura"; leitura.mkdir()
    (leitura / "levantamento.md").write_text("# o que eu medi\n")
    tid3 = claimed(conn, workspace_kind="dir", workspace_path=str(leitura))
    r3 = kb.complete_task(conn, tid3, summary="li, medi, relatei")
    st3 = kb.get_task(conn, tid3).status
    print(f"  workspace nao-git: {leitura}")
    print(f"  RESULTADO: complete_task={r3}  status={st3}")
    if r3 and st3 == "done":
        ok.append(3)
    else:
        print("  <-- ERRADO (o gate virou paranoia)")

    # ------------------------------------------------------------------- 4
    cabecalho(4, "metadata com SHA inventado", "RECUSAR")
    d4 = RAIZ / "c4"; d4.mkdir()
    proj4 = repo_com_origin(d4)
    tid4 = claimed(conn, workspace_kind="dir", workspace_path=str(proj4))
    inventado = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    try:
        kb.complete_task(conn, tid4, summary="entreguei",
                         metadata={"commit": inventado})
        print("  RESULTADO: FECHOU  <-- ERRADO")
    except kb.UnknownShaError as e:
        print(f"  SHA declarado: {inventado}")
        print(f"  RESULTADO: RECUSOU\n  mensagem ao worker:\n    {e}")
        print(f"  status do card: {kb.get_task(conn, tid4).status}")
        ok.append(4)

print()
print("=" * 76)
print(f"VEREDITO: {len(ok)}/4 controles conformes  (conformes: {ok})")
print("=" * 76)
sys.exit(0 if len(ok) == 4 else 1)
