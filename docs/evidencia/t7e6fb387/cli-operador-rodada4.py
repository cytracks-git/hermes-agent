"""O gate no caminho do OPERADOR (`hermes kanban complete`), incluindo o bypass B4.

Origem: o revisor escreveu `/tmp/rev3_t7e/cli_operador.py` para fechar o item 5
da rodada 1 (o CLI nunca tinha sido exercitado, so a API). 12-E: ferramenta que
mede fica no repositorio, senao morre com a maquina e nao passa por revisor.

Esta versao acrescenta o caso da rodada 4: o contorno de UMA LINHA
(`git checkout <branch-publicada>`) no caminho do operador. O gate tem de valer
nos dois caminhos — API e CLI — e a recusa tem de sair como MENSAGEM, nao
traceback.

Cenarios, cada um com o controle pareado:

  A  trabalho NAO empurrado, HEAD na branch suja  -> RECUSA (exit!=0)
  A' CONTROLE: o mesmo card depois do `git push`  -> FECHA  (exit 0)
  B  commit em `trabalho`, `git checkout main`    -> RECUSA (o bypass B4)
  B' CONTROLE: push antes do checkout             -> FECHA

Roda num HOME isolado: nao toca o board de producao.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ARVORE = str(Path(__file__).resolve().parents[3])
PY = f"{ARVORE}/.venv/bin/python"

PINS = (
    "HERMES_KANBAN_DB", "HERMES_KANBAN_BOARD", "HERMES_KANBAN_HOME",
    "HERMES_KANBAN_WORKSPACES_ROOT", "HERMES_KANBAN_LOGS_ROOT",
    "HERMES_KANBAN_TASK", "HERMES_KANBAN_WORKSPACE", "HERMES_KANBAN_RUN_ID",
    "HERMES_KANBAN_CLAIM_LOCK", "HERMES_DELEGATED_CHILD_CONTEXT",
    "HERMES_SUPERVISED_CHILD",
)

RAIZ = Path(tempfile.mkdtemp(prefix="cli-operador-r4-"))
HOME = RAIZ / ".hermes"
HOME.mkdir(parents=True)

env = dict(os.environ)
for v in PINS:
    env.pop(v, None)
env["HERMES_HOME"] = str(HOME)


def git(*a: str) -> str:
    r = subprocess.run(["git", *a], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, f"git {' '.join(a)}: {r.stderr}"
    return r.stdout


def repo_base(nome: str) -> tuple[Path, Path]:
    origin = RAIZ / f"{nome}-origin.git"
    git("init", "--bare", "-b", "main", str(origin))
    proj = RAIZ / nome
    git("clone", str(origin), str(proj))
    git("-C", str(proj), "config", "user.email", "t@example.com")
    git("-C", str(proj), "config", "user.name", "t")
    (proj / "README.md").write_text("base\n", encoding="utf-8")
    git("-C", str(proj), "add", "README.md")
    git("-C", str(proj), "commit", "-m", "init")
    git("-C", str(proj), "push", "origin", "HEAD:main")
    return proj, origin


def criar_card(proj: Path) -> str:
    codigo = f'''
import sys
sys.path.insert(0, {ARVORE!r})
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
kb._INITIALIZED_PATHS.clear(); kb.init_db()
with kbc.connect() as conn:
    tid = kb.create_task(conn, title="cli", assignee="worker")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET workspace_kind=?, workspace_path=?, "
                     "status='ready' WHERE id=?", ("dir", {str(proj)!r}, tid))
    print(tid)
'''
    r = subprocess.run([PY, "-c", codigo], env=env, capture_output=True,
                       text=True, cwd=ARVORE, timeout=300)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip().splitlines()[-1]


def status(tid: str) -> str:
    codigo = f'''
import sys
sys.path.insert(0, {ARVORE!r})
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
kb._INITIALIZED_PATHS.clear()
with kbc.connect() as conn:
    print(kb.get_task(conn, {tid!r}).status)
'''
    r = subprocess.run([PY, "-c", codigo], env=env, capture_output=True,
                       text=True, cwd=ARVORE, timeout=300)
    return r.stdout.strip() or f"(erro: {r.stderr[-200:]})"


def completar(tid: str, resumo: str):
    return subprocess.run(
        [PY, "-m", "hermes_cli.main", "kanban", "complete", tid, "--summary", resumo],
        env=env, capture_output=True, text=True, cwd=ARVORE, timeout=300)


def cenario(titulo: str, esperado: str, montar) -> bool:
    print("=" * 78)
    print(f"{titulo}")
    print(f"ESPERADO: {esperado}")
    print("=" * 78)
    tid, proj = montar()
    r = completar(tid, "Implementei, testei, tudo passou.")
    saida = ((r.stdout or "") + (r.stderr or "")).strip()
    print(f"  exit_code = {r.returncode}")
    for linha in saida.splitlines()[-6:]:
        print(f"    {linha}")
    est = status(tid)
    print(f"  status do card: {est}")
    tem_traceback = "Traceback (most recent call last)" in saida
    if tem_traceback:
        print("  !! TRACEBACK no caminho do operador — mensagem, nao stack trace")
    obtido = "RECUSOU" if r.returncode != 0 else "FECHOU"
    ok = (obtido == esperado) and not tem_traceback
    print(f"  => {'OK' if ok else 'NAO CONFORME'} (obtido={obtido})\n")
    return ok


def main() -> int:
    conformes = []

    def cenario_a():
        proj, _ = repo_base("a")
        tid = criar_card(proj)
        git("-C", str(proj), "checkout", "-b", "trabalho")
        (proj / "entrega.py").write_text("# 8 horas\n", encoding="utf-8")
        git("-C", str(proj), "add", "entrega.py")
        git("-C", str(proj), "commit", "-m", "trabalho")
        return tid, proj

    conformes.append(cenario(
        "A  card com trabalho NAO empurrado (HEAD na branch suja)",
        "RECUSOU", cenario_a))

    def cenario_a_linha():
        proj, _ = repo_base("a2")
        tid = criar_card(proj)
        git("-C", str(proj), "checkout", "-b", "trabalho")
        (proj / "entrega.py").write_text("# 8 horas\n", encoding="utf-8")
        git("-C", str(proj), "add", "entrega.py")
        git("-C", str(proj), "commit", "-m", "trabalho")
        git("-C", str(proj), "push", "-u", "origin", "trabalho")
        return tid, proj

    conformes.append(cenario(
        "A' CONTROLE POSITIVO: o mesmo cenario depois do `git push`",
        "FECHOU", cenario_a_linha))

    def cenario_b():
        proj, _ = repo_base("b")
        tid = criar_card(proj)
        git("-C", str(proj), "checkout", "-b", "trabalho")
        (proj / "entrega.py").write_text("# 8 horas\n", encoding="utf-8")
        git("-C", str(proj), "add", "entrega.py")
        git("-C", str(proj), "commit", "-m", "trabalho")
        git("-C", str(proj), "checkout", "main")  # O BYPASS DE UMA LINHA
        return tid, proj

    conformes.append(cenario(
        "B  o bypass B4: `git checkout main` antes de fechar",
        "RECUSOU", cenario_b))

    def cenario_b_linha():
        proj, _ = repo_base("b2")
        tid = criar_card(proj)
        git("-C", str(proj), "checkout", "-b", "trabalho")
        (proj / "entrega.py").write_text("# 8 horas\n", encoding="utf-8")
        git("-C", str(proj), "add", "entrega.py")
        git("-C", str(proj), "commit", "-m", "trabalho")
        git("-C", str(proj), "push", "-u", "origin", "trabalho")
        git("-C", str(proj), "checkout", "main")
        return tid, proj

    conformes.append(cenario(
        "B' CONTROLE POSITIVO: mesmo checkout, com push antes",
        "FECHOU", cenario_b_linha))

    print("=" * 78)
    print(f"VEREDITO: {sum(conformes)}/{len(conformes)} conformes")
    print("=" * 78)
    return 0 if all(conformes) else 1


if __name__ == "__main__":
    sys.exit(main())
