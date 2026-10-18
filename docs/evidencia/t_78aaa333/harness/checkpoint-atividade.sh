#!/bin/sh
# Checkpoint das atividades que a janela de rollout do Desktop vai atingir
# (restricao H1, 1139: "salvar checkpoint/IDs ... retomar somente essas
# atividades, do checkpoint, sem duplicar runs").
#
# Grava IDs e marcas d'agua ANTES de fechar o app, e reconfere DEPOIS. A
# comparacao e por CONTEUDO (id + contagem de mensagens + ultimo timestamp),
# nao por "o app abriu": app aberto nao prova sessao intacta.
#
# Uso: checkpoint-atividade.sh <ANTES|DEPOIS> <arquivo-de-saida>
set -eu

ROTULO="${1:?rotulo (ANTES|DEPOIS)}"
SAIDA="${2:?arquivo de saida}"
STATE=/Users/farantes/.hermes/state.db
KDB=/Users/farantes/.hermes/kanban/boards/atlas/kanban.db

{
  echo "# CHECKPOINT $ROTULO  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "## sessoes desktop ABERTAS (id|msgs|ultimo_ts|titulo) — as que o fechamento atinge"
  sqlite3 -readonly "$STATE" "
    select s.id||'|'||s.message_count||'|'||cast(max(m.timestamp) as integer)||'|'||substr(coalesce(s.title,'-'),1,50)
    from sessions s join messages m on m.session_id=s.id
    where s.ended_at is null and s.source='desktop'
    group by s.id order by s.id"
  echo "## runs Kanban abertas (id|task|pid) — NAO atingidas (ppid=1), conferir que seguem vivas"
  sqlite3 -readonly "$KDB" "select id||'|'||task_id||'|'||coalesce(worker_pid,0) from task_runs where ended_at is null order by id"
  echo "## cron: jobs ativos por perfil (o ticker do app fica de fora quando o gateway serve o perfil)"
  for P in default arquiteto executor pesquisa revisor; do
    echo "$P|$(HERMES_HOME= /Users/farantes/.hermes/hermes-agent/venv/bin/hermes -p "$P" cron list --all 2>/dev/null | grep -c '\[active\]' || true)"
  done
  echo "## perfis servidos pelo gateway (se o gateway serve, o ticker do Desktop se recolhe)"
  sqlite3 -readonly "$STATE" "select 1" >/dev/null   # so para falhar cedo se o banco sumir
  grep -o '"served_profiles":\[[^]]*\]' /Users/farantes/.hermes/gateway_state.json || echo '(sem served_profiles)'
} > "$SAIDA"

echo "checkpoint $ROTULO gravado em $SAIDA"
cat "$SAIDA"
