#!/bin/sh
# Inventario de ATIVIDADE VIVA antes/depois da janela de rollout do Desktop
# (restricao H1, comentario 1139: "faz o pause seguro da atividade e depois
# retoma ela quando voltar").
#
# So le. A pergunta e "o que esta em voo AGORA e seria atingido se eu fechar o
# Hermes.app" -- nao "o que existe". Por isso separa, explicitamente:
#
#   ATINGIDO   = processo filho do Hermes.app (o backend `serve`) e as sessoes
#                que ele hospeda. Fecha junto, por desenho.
#   PRESERVADO = gateway (processo proprio, sobrevive ao app por desenho) e o
#                worker deste card (ppid=1, spawn do dispatcher, nao do app).
#
# Sessao "viva" aqui e sessao ABERTA (ended_at nulo) com mensagem recente -- nao
# basta existir a linha: uma sessao aberta ha dias sem mensagem nao e atividade.
#
# Uso: inventario-atividade.sh <ANTES|DEPOIS> [minutos-de-recencia]
set -eu

ROTULO="${1:?rotulo (ANTES|DEPOIS)}"
RECENTE_MIN="${2:-120}"
STATE=/Users/farantes/.hermes/state.db
KDB=/Users/farantes/.hermes/kanban/boards/atlas/kanban.db
APP=/Users/farantes/.hermes/hermes-agent/apps/desktop/release/mac-arm64/Hermes.app

echo "=== INVENTARIO DE ATIVIDADE $ROTULO  $(date -u +%Y-%m-%dT%H:%M:%SZ)  (recencia=${RECENTE_MIN}min)"

echo "--- [ATINGIDO] Hermes.app e o backend serve que ele hospeda"
ps -eo pid,ppid,lstart,command | grep -F "$APP/Contents/MacOS/Hermes" | grep -v grep | cut -c1-120 || echo "(app fora do ar)"
ps -eo pid,ppid,lstart,command | grep -E "hermes_cli.main .*serve" | grep -v grep | cut -c1-140 || echo "(sem backend serve)"

echo "--- [ATINGIDO] sessoes ABERTAS com mensagem nos ultimos ${RECENTE_MIN}min"
sqlite3 -readonly "$STATE" "
  select s.id||' | src='||coalesce(s.source,'-')
         ||' | msgs='||s.message_count
         ||' | ult='||datetime(max(m.timestamp),'unixepoch','localtime')
         ||' | '||substr(coalesce(s.title,'(sem titulo)'),1,42)
  from sessions s join messages m on m.session_id=s.id
  where s.ended_at is null
  group by s.id
  having max(m.timestamp) > strftime('%s','now') - ${RECENTE_MIN}*60
  order by max(m.timestamp) desc"

echo "--- [ATINGIDO] turno em voo? (ultima mensagem da sessao e do usuario = agente respondendo)"
sqlite3 -readonly "$STATE" "
  select s.id||' -> ultimo papel='||(
      select role from messages where session_id=s.id order by timestamp desc limit 1)
  from sessions s join messages m on m.session_id=s.id
  where s.ended_at is null
  group by s.id
  having max(m.timestamp) > strftime('%s','now') - ${RECENTE_MIN}*60"

echo "--- [ATINGIDO] o backend serve se declara ocupado?"
PORTA="$(lsof -nP -a -iTCP -sTCP:LISTEN -p "$(pgrep -f 'hermes_cli.main .*serve' | head -1)" 2>/dev/null | awk 'NR==2{split($9,a,":"); print a[2]}')" || PORTA=""
if [ -n "${PORTA:-}" ]; then
  echo "porta=$PORTA"
  curl -s -m 5 "http://127.0.0.1:$PORTA/api/status" | tr ',' '\n' \
    | grep -E '"(active_agents|gateway_busy|gateway_drainable|active_sessions)"' || echo "(status ilegivel)"
else
  echo "(sem backend serve escutando)"
fi

echo "--- [PRESERVADO] gateway (processo proprio; sobrevive ao app por desenho)"
ps -eo pid,lstart,command | grep -E "hermes_cli.main gateway run" | grep -v grep | cut -c1-120 || echo "(gateway fora do ar)"

echo "--- [PRESERVADO] workers do Kanban (spawn do dispatcher, ppid=1; nao sao filhos do app)"
sqlite3 -readonly "$KDB" "
  select 'card '||id||' status='||status||' assignee='||coalesce(assignee,'-')
         ||' pid='||coalesce(worker_pid,0)||' run='||coalesce(current_run_id,0)
  from tasks where status in ('running','ready','review','waiting_approval')"
sqlite3 -readonly "$KDB" "
  select 'run aberta '||id||' task='||task_id||' pid='||coalesce(worker_pid,0)
  from task_runs where ended_at is null"

echo "--- [PRESERVADO] cron: jobs ativos por perfil servido (o ticker vive no gateway)"
for P in default arquiteto executor pesquisa revisor; do
  N="$(HERMES_HOME= /Users/farantes/.hermes/hermes-agent/venv/bin/hermes -p "$P" cron list --all 2>/dev/null | grep -c '\[active\]' || true)"
  echo "perfil $P: $N job(s) ativo(s)"
done

echo "=== FIM INVENTARIO $ROTULO"
