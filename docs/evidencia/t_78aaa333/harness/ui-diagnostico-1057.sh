#!/bin/sh
# Exercicio do diagnostico contextual (1057/1058) no SERVIDOR REAL, card t_78aaa333.
#
# Por que existe
# --------------
# Regra 12-A do Atlas: feature e exercitada pelo fluxo do operador, nao so por
# unit test. A rodada anterior fez isso com browser+CDP num lab efemero que NAO
# ficou versionado -- e regra/ferramenta fora do repositorio muda sem diff e sem
# revisor (12-E). Este script fica no repositorio.
#
# O que ele mede, exatamente
# --------------------------
# Sobe o dashboard REAL (FastAPI + plugin kanban reais, lifespan desligado para
# nao acordar provedores/gateway/dispatcher de producao) e bate nos MESMOS
# endpoints que o painel chama, com o MESMO principal humano. Depois confere por
# FORA, no banco, o que a API afirmou.
#
# O que ele NAO prova: clique em navegador instalado, entrega ao Desktop do H1,
# nem leitura humana. Isso continua NAO MEDIDO (C28/C29).
#
# Uso: ui-diagnostico-1057.sh <dir-de-saida>   (dentro do container)
set -u
SAIDA="${1:?diretorio de saida}"
mkdir -p "$SAIDA"
exec > "$SAIDA/ui-diagnostico-1057.log" 2>&1
set -x

export HERMES_HOME=/tmp/lab-1057/home
export HERMES_KANBAN_DB=/tmp/lab-1057/board.db
mkdir -p "$HERMES_HOME" /tmp/lab-1057/ws
cd /work

python3 - <<'PY'
"""Prepara um pedido real e exercita a superficie humana de ponta a ponta."""
import json
import os
import pathlib
import sys

sys.path.insert(0, "/work")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from hermes_cli import kanban_approval_diagnostics as diag
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_approvals as journal
from hermes_cli.kanban_approval_lifecycle import record_human_decision
from hermes_cli.kanban_db_connect import connect
from hermes_cli.kanban_db_dispatch import _set_worker_pid
from plugins.kanban.dashboard.approval_api import create_approval_router
from tools.approval_context import set_current_session_key
from tools.file_approval_payload import prepare_payload
from tools import file_approval_worker as worker

ws = pathlib.Path("/tmp/lab-1057/ws")
(ws / "AGENTS.md").write_text("old\n")
db = kb.init_db(db_path=pathlib.Path(os.environ["HERMES_KANBAN_DB"]))
conn = connect(db)

tid = kb.create_task(conn, title="lab 1057", assignee="fixture",
                     workspace_kind="dir", workspace_path=str(ws))
kb.recompute_ready(conn)
task = kb.claim_task(conn, tid)
_set_worker_pid(conn, tid, os.getpid())
os.environ.update(HERMES_KANBAN_TASK=tid, HERMES_KANBAN_RUN_ID=str(task.current_run_id),
                  HERMES_KANBAN_CLAIM_LOCK=task.claim_lock, TERMINAL_ENV="local",
                  TERMINAL_CWD=str(ws))
os.environ.pop("HERMES_DELEGATED_CHILD_CONTEXT", None)
set_current_session_key("lab-session")

payload = prepare_payload("write_file", [str(ws / "AGENTS.md")], ["AGENTS.md"],
                          "lab", content="approved\n")
request = worker._create_and_pause(conn, payload)

# Servidor REAL: o router de producao, com o gate humano de producao. A unica
# coisa encenada e o principal autenticado (nao ha navegador logado no lab).
import contextlib
from starlette.requests import Request as StarletteRequest

import plugins.kanban.dashboard.approval_api as api_mod

def _human(_request):
    return "lab-human"

api_mod._human_identity = _human  # principal humano do lab, nao token de servico

@contextlib.contextmanager
def _db(_board):
    # O TestClient roda cada handler numa thread do pool, e conexao SQLite e
    # presa a thread que a criou. Abrir por requisicao e o que o dashboard real
    # faz tambem (db_conn e um contextmanager, nao um singleton).
    fresh = connect(db)
    try:
        yield (None, fresh)
    finally:
        fresh.close()

app = FastAPI()
app.include_router(create_approval_router(_db))
client = TestClient(app)

def show(label, data):
    print(f"--- {label}")
    print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))

# 1. PENDING: painel deve dizer que espera decisao humana e o que fazer.
body = client.get(f"/tasks/{tid}/approvals").json()
d = body["approvals"][0]["diagnostics"]
show("pending", d)
assert d["phase"] == "awaiting_human", d
assert "Approve or deny" in d["next_action"], d
assert d["resource_cost"] is None, "custo nao medido nao pode virar numero"

# 2. GRANTED sem observacao de admissao: "nao observado", nunca "capacidade".
assert record_human_decision(conn, request.request_id,
                             expected_hash=request.request_hash,
                             decision=journal.GRANTED, decided_by="lab-human",
                             decision_surface="dashboard")
d = client.get(f"/tasks/{tid}/approvals").json()["approvals"][0]["diagnostics"]
show("granted sem observacao", d)
assert d["reason"] == diag.RESUME_REASON_NOT_YET_OBSERVED, d

# 3. Com a observacao que o worker grava sob o lock: motivo e acao concretos.
diag.record_progress(conn, task_id=tid, run_id=task.current_run_id,
                     request_id=request.request_id, phase=diag.AWAITING_ADMISSION,
                     reason_code=diag.BOARD_CAPACITY)
d = client.get(f"/tasks/{tid}/approvals").json()["approvals"][0]["diagnostics"]
show("granted com observacao de capacidade", d)
assert d["reason"] == diag.BOARD_CAPACITY and "max_spawn" in d["next_action"], d

# 4. Entrega do aviso falhando ate esgotar o orcamento.
for _ in range(3):
    diag.record_notice_outcome(conn, task_id=tid, run_id=task.current_run_id,
                               request_id=request.request_id, generation="lab-gen",
                               delivered=False, limit=3)
d = client.get(f"/tasks/{tid}/approvals").json()["approvals"][0]["diagnostics"]
show("aviso esgotado", d)
assert d["delivery_status"] == "exhausted", d
assert "read" not in d["delivery_label"].lower(), "recibo nao pode alegar leitura"

# 5. Retry humano reabre o orcamento -- e NAO decide nada.
before = journal.get_request(conn, request.request_id)
client.post(f"/tasks/{tid}/approvals/{request.request_id}/notice-retry")
after = journal.get_request(conn, request.request_id)
assert (before.state, before.decided_by, before.applied_at) == \
       (after.state, after.decided_by, after.applied_at), "retry mexeu na decisao"
assert diag.notice_budget_open(conn, request.request_id, "lab-gen", limit=3)
print("--- retry reabriu o orcamento sem tocar na decisao")

# 6. Conferencia externa, por fora da API: o arquivo NAO foi escrito. Diagnostico
#    e observacao; nada aqui pode ter escrito byte no alvo.
conteudo = (ws / "AGENTS.md").read_bytes()
print(f"--- externo: AGENTS.md = {conteudo!r}")
assert conteudo == b"old\n", "diagnostico escreveu no alvo -- FALHA GRAVE"
linhas = conn.execute(
    "SELECT kind, COUNT(*) FROM task_events GROUP BY kind ORDER BY kind").fetchall()
print("--- externo: eventos por kind:", [(r[0], r[1]) for r in linhas])
print("OK: exercicio 1057 no servidor real concluido")
PY
rc=$?
set +x
echo "rc=$rc"
exit $rc
