"""Controle negativo/positivo do gate contra o REPO e o REMOTO de verdade.

O que e real aqui (o que a prova mede):
  - o worktree /Users/farantes/atlas/wt/t7e6fb387-direto, com commit de verdade;
  - o remoto github.com/NousResearch/hermes-agent, consultado por rede;
  - o codigo do gate exatamente como vai para revisao.

O que e isolado: o kanban.db. Ele mora num HERMES_HOME temporario porque a
sessao worker que roda esta prova ja segura o lock do banco de producao —
medido: o processo ficava em espera de lock indefinidamente. O banco nao e o
sujeito da medicao; o par (repo, remoto) e.

Os quatro casos que o card exige:
  N1 commit local, rama NAO empurrada  -> RECUSA
  P1 mesmo card depois do push         -> FECHA
  P2 card de leitura pura (sem commit) -> FECHA
  N2 metadata com SHA inventado        -> RECUSA
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/Users/farantes/atlas/wt/t7e6fb387-direto")

_HOME = Path(tempfile.mkdtemp(prefix="gate-prova-"))
os.environ["HERMES_HOME"] = str(_HOME / ".hermes")
(_HOME / ".hermes").mkdir(parents=True, exist_ok=True)
# Esta prova roda DENTRO de uma sessao worker do kanban; sem limpar estas
# variaveis o proprio Hermes recusa criar o card de teste ("delegate_task child
# contexts cannot mutate Kanban tasks"). O board aqui e descartavel — o sujeito
# da medicao e o par (repo real, remoto real).
for _v in ("HERMES_KANBAN_TASK", "HERMES_KANBAN_DB", "HERMES_KANBAN_BOARD",
           "HERMES_KANBAN_WORKSPACE", "HERMES_DELEGATED_CHILD",
           "HERMES_SUBAGENT", "HERMES_DELEGATE_CHILD"):
    os.environ.pop(_v, None)

from hermes_cli import kanban_db as kb          # noqa: E402
from hermes_cli import kanban_db_connect as kbc  # noqa: E402

WT = "/Users/farantes/atlas/wt/t7e6fb387-direto"


def _task(conn, workspace_path, kind="worktree"):
    tid = kb.create_task(conn, title="prova-gate", assignee="worker")
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET status='ready', workspace_kind=?, workspace_path=? WHERE id=?",
            (kind, workspace_path, tid),
        )
    kb.claim_task(conn, tid, claimer="worker")
    return tid


def tentar(rotulo, workspace_path, metadata, kind="worktree"):
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    with kbc.connect_closing() as conn:
        tid = _task(conn, workspace_path, kind)
        try:
            kb._gate_completion_evidence(conn, tid, metadata, "prova round2")
            print(f"{rotulo}\n    -> FECHARIA (gate nao recusou)\n")
        except kb.UnpushedWorkError as e:
            print(f"{rotulo}\n    -> RECUSOU [UnpushedWorkError]\n       {e}\n")
        except kb.UnknownShaError as e:
            print(f"{rotulo}\n    -> RECUSOU [UnknownShaError]\n       {e}\n")
        except kb.UnmeasuredEvidenceError as e:
            print(f"{rotulo}\n    -> RECUSOU [UnmeasuredEvidenceError]\n       {e}\n")


if __name__ == "__main__":
    caso = sys.argv[1] if len(sys.argv) > 1 else "todos"
    if caso in ("n1", "p1", "todos"):
        tentar("[N1/P1] worktree REAL, rama do card", WT, {})
    if caso in ("p2", "todos"):
        scratch = Path(tempfile.mkdtemp(prefix="scratch-leitura-"))
        (scratch / "achados.md").write_text("so medi, nao commitei\n")
        tentar(
            "[P2] leitura pura: workspace scratch nao-git, sem commit",
            str(scratch), {"findings": "so medi"}, kind="scratch",
        )
    if caso in ("n2", "todos"):
        tentar(
            "[N2] SHA inventado em metadata", WT,
            {"commit": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"},
        )

