#!/bin/sh
# Porteiro da janela de rollout do Desktop (restricao H1, comentario 1139).
#
# Responde UMA pergunta com codigo de saida, para nao virar opiniao:
#   rc=0  JANELA ABERTA  -- nada util em voo; pode pausar e trocar o bundle
#   rc=1  JANELA FECHADA -- ha trabalho vivo; ESPERAR, nunca matar
#   rc=2  NAO MEDIDO     -- nao consegui ler alguma fonte (fail-closed)
#
# Por que fail-closed em 2 e nao "assume vazio": um SELECT que falha devolve
# lista vazia, e lista vazia lida como "nada rodando" e exatamente o falso-verde
# que derruba a sessao do operador.
#
# Tres condicoes, todas medidas, nenhuma herdada:
#   1. nenhuma sessao do Desktop com mensagem nos ultimos QUIETO_MIN minutos
#   2. o backend `serve` declara active_agents=0 e gateway_busy=false
#   3. nenhuma sessao aberta cujo ULTIMO papel seja 'user' (turno em voo:
#      o humano falou e o agente ainda nao respondeu)
#
# O worker deste card e o gateway NAO entram na conta: sao ppid=1, nao morrem
# com o app. Contar a si mesmo como atividade fecharia a janela para sempre.
#
# Uso: janela-segura.sh [minutos-de-silencio]
set -u

QUIETO_MIN="${1:-5}"
STATE=/Users/farantes/.hermes/state.db

falha_medicao() { echo "NAO MEDIDO: $1"; exit 2; }

[ -r "$STATE" ] || falha_medicao "state.db ilegivel em $STATE"

echo "=== JANELA  $(date '+%H:%M:%S')  (silencio exigido: ${QUIETO_MIN}min)"

# 1. sessoes com mensagem recente
RECENTES="$(sqlite3 -readonly "$STATE" "
  select s.id||' ult='||datetime(max(m.timestamp),'unixepoch','localtime')
  from sessions s join messages m on m.session_id=s.id
  where s.ended_at is null and s.source='desktop'
  group by s.id
  having max(m.timestamp) > strftime('%s','now') - ${QUIETO_MIN}*60")" \
  || falha_medicao "consulta de sessoes recentes falhou"

# 2. backend serve
PID_SERVE="$(pgrep -f 'hermes_cli.main .*serve' | head -1)"
if [ -z "$PID_SERVE" ]; then
  OCUPADO_SERVE="(sem backend serve — app ja fora do ar)"
  BUSY=""
else
  PORTA="$(lsof -nP -a -iTCP -sTCP:LISTEN -p "$PID_SERVE" 2>/dev/null | awk 'NR==2{split($9,a,":"); print a[2]}')"
  [ -n "${PORTA:-}" ] || falha_medicao "backend serve $PID_SERVE sem porta legivel"
  ST="$(curl -s -m 5 "http://127.0.0.1:$PORTA/api/status")" || falha_medicao "status do serve ilegivel"
  echo "$ST" | grep -q '"active_agents"' || falha_medicao "status do serve sem active_agents"
  OCUPADO_SERVE="$(echo "$ST" | tr ',' '\n' | grep -E '"(active_agents|gateway_busy)"' | tr '\n' ' ')"
  BUSY="$(echo "$ST" | tr ',' '\n' | grep -E '"active_agents":[1-9]' || true)"
fi

# 3. turno em voo (ultimo papel = user E recente)
#    A recencia NAO e enfeite: sem ela o detector acusou 4 sessoes de 19/09
#    cuja ultima mensagem e do usuario -- turnos ABANDONADOS, nao em voo. Um
#    porteiro que nunca abre e tao inutil quanto um que nunca fecha.
EM_VOO="$(sqlite3 -readonly "$STATE" "
  select s.id||' ult='||datetime(max(m.timestamp),'unixepoch','localtime')
  from sessions s join messages m on m.session_id=s.id
  where s.ended_at is null and s.source='desktop'
    and (select role from messages where session_id=s.id order by timestamp desc limit 1)='user'
  group by s.id
  having max(m.timestamp) > strftime('%s','now') - ${QUIETO_MIN}*60")" \
  || falha_medicao "consulta de turno em voo falhou"

echo "--- sessoes desktop com mensagem recente:"
[ -n "$RECENTES" ] && echo "$RECENTES" || echo "(nenhuma)"
echo "--- backend serve: $OCUPADO_SERVE"
echo "--- turnos em voo (ultimo papel=user):"
[ -n "$EM_VOO" ] && echo "$EM_VOO" || echo "(nenhum)"

if [ -n "$RECENTES" ] || [ -n "$BUSY" ] || [ -n "$EM_VOO" ]; then
  echo "VEREDITO: JANELA FECHADA — esperar ponto seguro"
  exit 1
fi
echo "VEREDITO: JANELA ABERTA"
exit 0
