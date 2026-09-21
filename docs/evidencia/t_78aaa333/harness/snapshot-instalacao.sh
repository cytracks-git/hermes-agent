#!/bin/sh
# Snapshot ANTES/DEPOIS da promocao da instalacao compartilhada (rodada 1060).
#
# Le, nao escreve: SHA das duas arvores, estado do gateway, esquema e contagens
# do board, processos vivos. E o mesmo script nos dois lados da janela, para que
# a comparacao seja entre saidas do MESMO instrumento -- nao entre dois comandos
# parecidos escritos em momentos diferentes.
#
# Uso: snapshot-instalacao.sh <ANTES|DEPOIS>
set -eu

ROTULO="${1:?rotulo (ANTES|DEPOIS)}"
INST=/Users/farantes/.hermes/hermes-agent
WT=/Users/farantes/atlas/wt/kanban-aprovacao-interativa
DB=/Users/farantes/.hermes/kanban/boards/atlas/kanban.db

echo "=== SNAPSHOT $ROTULO  $(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "--- instalacao compartilhada ($INST)"
git -C "$INST" rev-parse HEAD
git -C "$INST" log --oneline -1
echo "porcelain:"
git -C "$INST" status --porcelain

echo "--- worktree do card ($WT)"
WT_SHA="$(git -C "$WT" rev-parse HEAD)"
INST_SHA="$(git -C "$INST" rev-parse HEAD)"
echo "$WT_SHA"
echo "porcelain (contagem): $(git -C "$WT" status --porcelain | wc -l | tr -d ' ')"

echo "--- fast-forward possivel? (instalado $INST_SHA ancestral do candidato $WT_SHA)"
# SHAs lidos AGORA das duas arvores: um SHA digitado a mao ja produziu um
# "NAO-ANCESTRAL" falso nesta rodada (erro de transcricao nos ultimos digitos).
if git -C "$INST" merge-base --is-ancestor "$INST_SHA" "$WT_SHA" 2>/dev/null; then
  echo "FAST-FORWARD OK ($(git -C "$INST" rev-list --count "$INST_SHA".."$WT_SHA" 2>/dev/null) commits a frente)"
else
  echo "NAO-ANCESTRAL"
fi

echo "--- marcador waiting_approval no arquivo da instalacao"
grep -c waiting_approval "$INST/hermes_cli/kanban_db.py" || echo 0
echo "--- coluna waiting_approval no painel da instalacao"
grep -c waiting_approval "$INST/plugins/kanban/dashboard/plugin_api.py" || echo 0

echo "--- gateway_state.json"
cat /Users/farantes/.hermes/gateway_state.json 2>/dev/null || echo "(ausente)"

echo "--- board: esquema da aprovacao"
sqlite3 "$DB" "select name from sqlite_master where name in ('approval_requests','idx_appr_one_pending_per_run','idx_events_task_kind') order by name"
echo "--- board: tasks por status"
sqlite3 "$DB" "select status||'='||count(*) from tasks group by status order by count(*) desc"
echo "--- board: contagens (runs / eventos / approval_requests)"
sqlite3 "$DB" "select (select count(*) from task_runs)||' / '||(select count(*) from task_events)||' / '||(select count(*) from approval_requests)"
echo "--- board: cards vivos (running/ready/waiting)"
sqlite3 "$DB" "select id||' '||status||' '||coalesce(assignee,'-')||' pid='||coalesce(worker_pid,0) from tasks where status in ('running','ready','waiting_approval')"

echo "--- processos vivos"
ps -o pid=,lstart=,command= -p 31800 2>/dev/null | cut -c1-120 || echo "(gateway 31800 ausente)"
ps -o pid=,lstart=,command= -p 56920 2>/dev/null | cut -c1-120 || echo "(serve 56920 ausente)"
pgrep -fl "hermes.*gateway" 2>/dev/null | cut -c1-120 || true

echo "=== FIM $ROTULO"
