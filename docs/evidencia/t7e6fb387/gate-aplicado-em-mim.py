"""O gate aplicado a MIM: o que ele diz do meu proprio worktree, agora?

Um gate que nao cobra do proprio autor nao vale nada. Isto roda a funcao real
(`_verify_repo_branches`) contra o worktree deste card — dados reais, nao
fixture.

MEDIDO com este script (rodada 4), e a leitura importa: com `origin` apontando
para `NousResearch/hermes-agent` (onde eu NAO tenho push), o gate me RECUSA,
porque e o `origin` que ele consulta. Depois de publicar no fork
`cytracks-git/hermes-agent`, ele so me aceita se o remoto consultado for o que
de fato anuncia o commit. Ou seja: o gate cobra de mim exatamente como cobra dos
outros, e nao aceita a minha palavra de que "esta empurrado".

SO LEITURA do repo. O board usado e isolado (HOME temporario): nao toca
producao.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ARVORE = Path(__file__).resolve().parents[3]

for v in ("HERMES_KANBAN_DB", "HERMES_KANBAN_BOARD", "HERMES_KANBAN_HOME",
          "HERMES_KANBAN_WORKSPACES_ROOT", "HERMES_KANBAN_LOGS_ROOT",
          "HERMES_KANBAN_TASK", "HERMES_KANBAN_WORKSPACE", "HERMES_KANBAN_RUN_ID",
          "HERMES_KANBAN_CLAIM_LOCK", "HERMES_DELEGATED_CHILD_CONTEXT",
          "HERMES_SUPERVISED_CHILD"):
    os.environ.pop(v, None)
HOME = Path(tempfile.mkdtemp(prefix="gate-em-mim-")) / ".hermes"
HOME.mkdir(parents=True)
os.environ["HERMES_HOME"] = str(HOME)

sys.path.insert(0, str(ARVORE))
from hermes_cli import kanban_db as kb  # noqa: E402
from hermes_cli import kanban_db_connect as kbc  # noqa: E402

kb._INITIALIZED_PATHS.clear()
kb.init_db()


def estado_real() -> None:
    """O que os remotos anunciam sobre o meu commit, medido por fora."""
    head = subprocess.run(["git", "-C", str(ARVORE), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=120).stdout.strip()
    print(f"  meu HEAD: {head}")
    for remoto in ("origin", "fork"):
        r = subprocess.run(
            ["git", "-C", str(ARVORE), "ls-remote", "--heads", remoto,
             "refs/heads/card/t7e6fb387-direto"],
            capture_output=True, text=True, timeout=300)
        anunciado = r.stdout.split("\t")[0].strip() if r.stdout.strip() else "(nao anuncia)"
        print(f"  {remoto:<7} -> {anunciado}")


def main() -> int:
    print("=" * 78)
    print("O GATE APLICADO A MIM MESMO")
    print("=" * 78)
    print(f"worktree: {ARVORE}\n")
    estado_real()

    with kbc.connect() as conn:
        tid = kb.create_task(conn, title="eu mesmo", assignee="executor")
        # Run com inicio bem antigo: a janela cobre TODO o trabalho deste card,
        # que e a condicao mais severa para mim.
        with kb.write_txn(conn):
            conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
            conn.execute(
                "INSERT INTO task_runs (task_id, status, started_at) VALUES (?,?,?)",
                (tid, "running", int(time.time()) - 86400 * 7),
            )
        try:
            achado = kb._verify_repo_branches(conn, tid, ARVORE)
        except kb.UnpushedWorkError as exc:
            print("\n  O GATE ME RECUSA:")
            print(f"    {exc}")
            print("\n  Leitura honesta: ele consulta `origin` (NousResearch), onde eu")
            print("  nao tenho permissao de push. O meu commit esta publicado no")
            print("  FORK, e o gate nao aceita isso como prova para `origin` — que")
            print("  e o comportamento correto: quem decide e o remoto perguntado,")
            print("  nao a minha alegacao de ter empurrado em algum lugar.")
            return 0
        except kb.UnmeasuredEvidenceError as exc:
            print(f"\n  NAO MEDIDO: {exc}")
            return 0

    print(f"\n  branches do card medidas: {achado or '(nenhuma pendente)'}")
    print("  O gate me ACEITA — o remoto consultado anuncia o meu commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
