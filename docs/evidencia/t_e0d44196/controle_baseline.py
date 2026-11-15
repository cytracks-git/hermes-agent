"""Controle do instrumento baseline.py (achado R1 do revisor em t_e0d44196).

Banco descartavel com schema real do kanban, em HERMES_HOME temporario. Nada
toca o board atlas. O evento auto e produzido pelo codigo de producao
(redispatch_transient_blocks), nao inserido a mao, para o contador medir o que
o C2 grava de verdade.

  positivo: card transient re-despachado pelo C2 -> auto_redespacho_eventos=1,
            retomados_auto=1, latencia auto ~ delay.
  negativo: card transient destravado por mao (unblock_task) -> conta em
            retomados_mao, NAO em auto.
  espelho:  baseline.AUTO_MARKER == kanban_db_transient.AUTO_MARKER.

Sai com rc=1 se qualquer asercao falhar. Uso (venv do Hermes):
  python controle_baseline.py <worktree>
"""
import os, shutil, sys, tempfile, time
from pathlib import Path

WT = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(WT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
tmp = Path(tempfile.mkdtemp(prefix="c2-controle-", dir=os.environ.get("TMPDIR")))
home = tmp / ".hermes"; (home / "kanban").mkdir(parents=True)
os.environ["HERMES_HOME"] = str(home)
os.environ.pop("HERMES_KANBAN_DB", None)
os.environ.pop("HERMES_KANBAN_BOARD", None)

import baseline
from hermes_cli import kanban_db as kb, kanban_db_connect as kbc, kanban_db_transient as kt

falhas = []


def confere(nome, ok, valor):
    print(("ok   " if ok else "FALHA"), nome, valor)
    if not ok:
        falhas.append(nome)


try:
    confere("espelho AUTO_MARKER", baseline.AUTO_MARKER == kt.AUTO_MARKER,
            (baseline.AUTO_MARKER, kt.AUTO_MARKER))
    conn = kbc.connect()
    db = conn.execute("PRAGMA database_list").fetchone()[2]
    t_auto = kb.create_task(conn, title="C2 controle auto", assignee="executor")
    t_mao = kb.create_task(conn, title="C2 controle mao", assignee="executor")
    for t in (t_auto, t_mao):
        kb.claim_task(conn, t)
        kb.block_task(conn, t, reason="controle C2", kind="transient")
    conn.execute("UPDATE task_events SET created_at = created_at - 700 WHERE task_id IN (?, ?)", (t_auto, t_mao))
    conn.commit()

    vazio = baseline.medir(db)
    confere("antes: auto_redespacho_eventos == 0", vazio["auto_redespacho_eventos"] == 0, vazio)

    # negativo: humano destrava t_mao
    kb.unblock_task(conn, t_mao)
    so_mao = baseline.medir(db)
    confere("negativo: unblock manual nao conta como auto",
            so_mao["auto_redespacho_eventos"] == 0 and so_mao["retomados_auto"] == 0
            and so_mao["retomados_mao"] == 1, so_mao)

    # positivo: C2 de producao re-despacha t_auto
    ids = kt.redispatch_transient_blocks(conn, delay_seconds=600, failure_limit=kb.DEFAULT_FAILURE_LIMIT,
                                         now=int(time.time()))
    confere("C2 retomou so o card transient parado", ids == [t_auto], ids)
    depois = baseline.medir(db)
    confere("positivo: auto_redespacho_eventos == 1", depois["auto_redespacho_eventos"] == 1, depois)
    confere("positivo: retomados_auto == 1 e retomados_mao == 1",
            depois["retomados_auto"] == 1 and depois["retomados_mao"] == 1, depois)
    lat = depois["latencia_auto_min_mediana"]
    confere("positivo: latencia auto entre 10 e 13 min", lat is not None and 10 <= lat <= 13, lat)
    conn.close()
finally:
    shutil.rmtree(tmp)
print("copia_removida:", not tmp.exists())
print("RESULTADO:", "PASSA" if not falhas else f"FALHA {falhas}")
sys.exit(1 if falhas else 0)
