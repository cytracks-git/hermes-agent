"""Harness do REVISOR (round 2, lente execucao). Nao edita a arvore sob revisao.

Cada caso imprime ESPERADO vs OBTIDO. Controle positivo primeiro: se o gate
nao recusar o caso obvio, os "ACEITOU" seguintes nao provam nada.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WT = "/Users/farantes/atlas/wt/t7e6fb387-direto"
sys.path.insert(0, WT)

# ISOLAMENTO ANTES DE QUALQUER IMPORT DO KANBAN.
#
# A versao original deste harness setava apenas HERMES_HOME por caso (classe
# Sandbox) e criou 10 cards `assignee=worker` no board atlas de PRODUCAO: o pin
# `HERMES_KANBAN_DB`, injetado em todo worker, VENCE HERMES_HOME. Tres desses
# fixtures ocuparam o teto de 4 slots do dispatcher enquanto 23 cards reais
# esperavam em `ready`. Medido em causa-colateral-board.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from isolar_board import afirmar_isolado, isolar_board  # noqa: E402

_RAIZ_ISOLADA = isolar_board("harness-revisor-")


def git(*args, check=True, cwd=None):
    r = subprocess.run(["git", *args], capture_output=True, text=True, timeout=120, cwd=cwd)
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout


class Sandbox:
    """HERMES_HOME isolado por caso, com o pin de board ja removido.

    O `isolar_board()` do topo do arquivo tirou `HERMES_KANBAN_DB` do ambiente
    uma vez; aqui cada caso ganha seu proprio HERMES_HOME e RECONFERE que o
    destino continua fora de qualquer board real antes de criar card.
    """

    def __init__(self, name):
        safe = "".join(c if c.isalnum() else "-" for c in name)[:24]
        self.root = Path(tempfile.mkdtemp(prefix=f"revt7e-{safe}-"))
        self.home = self.root / ".hermes"
        self.home.mkdir()
        os.environ["HERMES_HOME"] = str(self.home)
        self._orig_home = Path.home
        Path.home = staticmethod(lambda: self.root)  # type: ignore
        import hermes_cli.kanban_db as kb
        kb._INITIALIZED_PATHS.clear()
        afirmar_isolado()  # aborta se o destino nao estiver sob este HERMES_HOME
        kb.init_db()
        self.kb = kb

    def close(self):
        Path.home = self._orig_home  # type: ignore


def make_origin_and_clone(root: Path, name="project"):
    origin = root / "origin.git"
    git("init", "--bare", str(origin))
    proj = root / name
    git("clone", str(origin), str(proj))
    git("-C", str(proj), "config", "user.email", "t@example.com")
    git("-C", str(proj), "config", "user.name", "t")
    (proj / "README.md").write_text("hello\n")
    git("-C", str(proj), "add", "README.md")
    git("-C", str(proj), "commit", "-m", "init")
    git("-C", str(proj), "push", "origin", "HEAD")
    return origin, proj


def claimed(kb, conn, **cols):
    tid = kb.create_task(conn, title="t", assignee="worker")
    if cols:
        sets = ", ".join(f"{k}=?" for k in cols)
        with kb.write_txn(conn):
            conn.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*cols.values(), tid))
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
    assert kb.claim_task(conn, tid, claimer="worker") is not None
    return tid


def run_case(name, esperado, fn):
    sb = Sandbox(name)
    kb = sb.kb
    from hermes_cli import kanban_db_connect as kbc
    try:
        with kbc.connect_closing() as conn:
            try:
                ok = fn(sb, kb, conn)
                obtido = f"ACEITOU(status={ok})"
            except kb.UnpushedWorkError as e:
                obtido = f"RECUSOU UnpushedWorkError: {str(e)[:110]}"
            except kb.UnknownShaError as e:
                obtido = f"RECUSOU UnknownShaError: {str(e)[:110]}"
            except kb.UnmeasuredEvidenceError as e:
                obtido = f"RECUSOU UnmeasuredEvidenceError({e.reason}): {e.detail[:90]}"
    except Exception as e:  # noqa
        obtido = f"ERRO {type(e).__name__}: {e}"
    finally:
        sb.close()
    veredito = "OK  " if obtido.startswith(esperado) else "FALHA"
    print(f"{veredito} {name}  esperado={esperado}  obtido={obtido}")
    return veredito == "OK  "


# ---------------------------------------------------------------- casos


def caso_W0_controle(sb, kb, conn):
    """CONTROLE POSITIVO: commit local nao empurrado, worktree do card. Tem de RECUSAR."""
    origin, proj = make_origin_and_clone(sb.root)
    tid = claimed(kb, conn)
    wt = proj / ".worktrees" / tid
    from hermes_cli import kanban_db_workspace as kbw
    kbw._ensure_git_worktree(proj, wt, f"wt/{tid}")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET workspace_kind='worktree', workspace_path=? WHERE id=?",
                     (str(wt), tid))
    (wt / "f.txt").write_text("x")
    git("-C", str(wt), "add", "f.txt")
    git("-C", str(wt), "commit", "-m", "local")
    kb.complete_task(conn, tid, summary="trabalho local")
    return kb.get_task(conn, tid).status


def caso_W1_scratch_omite_metadata(sb, kb, conn):
    """Worker scratch trabalha num worktree EXTERNO e NAO declara nada em metadata.

    O teste X1 do autor declara `metadata={'worktree': ...}`. Aqui o worker
    simplesmente cala. Se fechar, omitir continua sendo o atalho.
    """
    origin, proj = make_origin_and_clone(sb.root)
    scratch = sb.root / "scratch-ws"
    scratch.mkdir()
    tid = claimed(kb, conn, workspace_kind="scratch", workspace_path=str(scratch))
    externo = proj / ".worktrees" / f"ext-{tid}"
    from hermes_cli import kanban_db_workspace as kbw
    kbw._ensure_git_worktree(proj, externo, f"wt/ext-{tid}")
    (externo / "f.txt").write_text("x")
    git("-C", str(externo), "add", "f.txt")
    git("-C", str(externo), "commit", "-m", "local nao empurrado")
    # worker NAO declara o worktree, NAO declara sha
    kb.complete_task(conn, tid, summary="Implementei, testei, tudo passou.")
    return kb.get_task(conn, tid).status


def caso_W2_forja_update_ref(sb, kb, conn):
    """X2 do autor: refs/remotes forjada sem push. Tem de RECUSAR."""
    origin, proj = make_origin_and_clone(sb.root)
    tid = claimed(kb, conn)
    wt = proj / ".worktrees" / tid
    from hermes_cli import kanban_db_workspace as kbw
    kbw._ensure_git_worktree(proj, wt, f"wt/{tid}")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET workspace_kind='worktree', workspace_path=? WHERE id=?",
                     (str(wt), tid))
    (wt / "f.txt").write_text("x")
    git("-C", str(wt), "add", "f.txt")
    git("-C", str(wt), "commit", "-m", "local")
    head = git("-C", str(wt), "rev-parse", "HEAD").strip()
    git("-C", str(wt), "update-ref", "refs/remotes/origin/forjado", head)
    kb.complete_task(conn, tid, summary="forjei refs/remotes")
    return kb.get_task(conn, tid).status


def caso_W3_remoto_forjado_pelo_worker(sb, kb, conn):
    """O worker NAO controla a RESPOSTA do remoto -- mas controla QUAL remoto.

    Cria um bare repo local descartavel, aponta origin para ele, empurra.
    O ls-remote responde 'sim, esta publicado'. O trabalho continua so no disco.
    """
    origin, proj = make_origin_and_clone(sb.root)
    tid = claimed(kb, conn)
    wt = proj / ".worktrees" / tid
    from hermes_cli import kanban_db_workspace as kbw
    kbw._ensure_git_worktree(proj, wt, f"wt/{tid}")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET workspace_kind='worktree', workspace_path=? WHERE id=?",
                     (str(wt), tid))
    (wt / "f.txt").write_text("x")
    git("-C", str(wt), "add", "f.txt")
    git("-C", str(wt), "commit", "-m", "local")
    head = git("-C", str(wt), "rev-parse", "HEAD").strip()
    # A FORJA: remoto de mentira, criado pelo proprio worker, no mesmo disco.
    fake = sb.root / "remoto-de-mentira.git"
    git("init", "--bare", str(fake))
    git("-C", str(wt), "remote", "set-url", "origin", str(fake))
    git("-C", str(wt), "push", "origin", "HEAD")
    anunciado_real = git("-C", str(proj), "ls-remote", str(origin))
    assert head not in anunciado_real, "pre-condicao: o origin REAL nao tem o commit"
    kb.complete_task(conn, tid, summary="empurrei (para um remoto que eu inventei)")
    return kb.get_task(conn, tid).status


def caso_W4_arquivos_nao_commitados(sb, kb, conn):
    """A classe do card inclui '53 arquivos em /tmp' -- trabalho NAO commitado.

    Worktree limpo do ponto de vista de commits (HEAD publicado), mas com
    arquivos novos nao commitados. O cleanup do workspace apaga.
    """
    origin, proj = make_origin_and_clone(sb.root)
    tid = claimed(kb, conn)
    wt = proj / ".worktrees" / tid
    from hermes_cli import kanban_db_workspace as kbw
    kbw._ensure_git_worktree(proj, wt, f"wt/{tid}")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET workspace_kind='worktree', workspace_path=? WHERE id=?",
                     (str(wt), tid))
    git("-C", str(wt), "push", "origin", "HEAD:refs/heads/wt-" + tid)
    (wt / "trabalho-de-8-horas.py").write_text("# nao commitado\n")
    kb.complete_task(conn, tid, summary="Entreguei. 53 arquivos novos.")
    return kb.get_task(conn, tid).status


def caso_W5_mentira_pura_em_summary(sb, kb, conn):
    """Worktree com HEAD publicado; summary mente sobre testes. Tem de FECHAR (fora do recorte)."""
    origin, proj = make_origin_and_clone(sb.root)
    tid = claimed(kb, conn)
    wt = proj / ".worktrees" / tid
    from hermes_cli import kanban_db_workspace as kbw
    kbw._ensure_git_worktree(proj, wt, f"wt/{tid}")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET workspace_kind='worktree', workspace_path=? WHERE id=?",
                     (str(wt), tid))
    git("-C", str(wt), "push", "origin", "HEAD:refs/heads/wt-" + tid)
    kb.complete_task(conn, tid, summary="Rodei a suite: 31 passed in 2.14s, exit code 0")
    return kb.get_task(conn, tid).status


def caso_W6_leitura_pura(sb, kb, conn):
    """Controle do recorte: leitura pura fecha (nao pode virar paranoia)."""
    scratch = sb.root / "leitura"
    scratch.mkdir()
    (scratch / "notas.md").write_text("levantei\n")
    tid = claimed(kb, conn, workspace_kind="scratch", workspace_path=str(scratch))
    kb.complete_task(conn, tid, summary="li e medi")
    return kb.get_task(conn, tid).status


def caso_W7_sha_inventado(sb, kb, conn):
    """Controle: SHA tipado inventado tem de RECUSAR."""
    origin, proj = make_origin_and_clone(sb.root)
    tid = claimed(kb, conn)
    wt = proj / ".worktrees" / tid
    from hermes_cli import kanban_db_workspace as kbw
    kbw._ensure_git_worktree(proj, wt, f"wt/{tid}")
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET workspace_kind='worktree', workspace_path=? WHERE id=?",
                     (str(wt), tid))
    git("-C", str(wt), "push", "origin", "HEAD:refs/heads/wt-" + tid)
    kb.complete_task(conn, tid, summary="pronto",
                     metadata={"commit": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"})
    return kb.get_task(conn, tid).status


if __name__ == "__main__":
    casos = [
        ("W0 controle positivo (commit local, sem push)", "RECUSOU", caso_W0_controle),
        ("W2 forja update-ref refs/remotes (bloq.1 rodada1)", "RECUSOU", caso_W2_forja_update_ref),
        ("W7 SHA tipado inventado", "RECUSOU", caso_W7_sha_inventado),
        ("W6 leitura pura scratch nao-git", "ACEITOU", caso_W6_leitura_pura),
        ("W1 scratch + worktree externo, worker OMITE metadata", "RECUSOU", caso_W1_scratch_omite_metadata),
        ("W3 worker aponta origin para bare repo que ele criou", "RECUSOU", caso_W3_remoto_forjado_pelo_worker),
        ("W4 HEAD publicado + arquivos NAO commitados", "RECUSOU", caso_W4_arquivos_nao_commitados),
        ("W5 HEAD publicado + summary mentiroso", "ACEITOU", caso_W5_mentira_pura_em_summary),
    ]
    conformes = 0
    for nome, esp, fn in casos:
        if run_case(nome, esp, fn):
            conformes += 1
    print(f"\nconformes: {conformes}/{len(casos)}")
