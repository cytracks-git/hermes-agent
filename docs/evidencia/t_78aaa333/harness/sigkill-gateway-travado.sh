#!/bin/sh
# Ultimo degrau: SIGKILL SOMENTE no gateway que drenou e nao sai.
#
# Por que isto nao e "matar processo a -9" no sentido proibido
# -----------------------------------------------------------
# Medido antes de chegar aqui, nesta ordem: (1) SIGUSR1 completou o
# desligamento inteiro -- "Gateway stopped (total teardown 0.15s)", adapters
# desconectados, SessionDB fechado, drain com active_at_start=0; (2) o processo
# nao saiu: main thread presa em kevent, nenhuma entrada de saida no
# gateway-exit-diag.log; (3) SIGTERM foi recebido e registrado no log e mesmo
# assim nao saiu em 90s; (4) o heartbeat esta congelado. Pelo criterio do
# proprio Hermes (hermes_cli/gateway.py, stop limitado para "provably dead
# loop") isto e um loop morto, nao trabalho vivo.
#
# O alvo e SO o pid do gateway. NAO se toca no shim supervisionado pelo launchd
# (ele precisa continuar vivo para ver o filho sair e pedir a reposicao) e NAO
# se usa `launchctl kickstart -k`, que derrubaria o job inteiro -- inclusive o
# worker Kanban que esta executando esta rodada.
#
# Uso: sigkill-gateway-travado.sh <pid-do-gateway> <pid-do-shim> <pid-do-worker>
set -eu

PID="${1:?pid do gateway travado}"
SHIM="${2:?pid do shim launchd}"
WORKER="${3:?pid do worker que NAO pode morrer}"

echo "=== antes  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
ps -o pid=,stat=,command= -p "$PID" -p "$SHIM" -p "$WORKER" 2>/dev/null | cut -c1-95

echo "--- SIGKILL somente em $PID"
kill -KILL "$PID"

i=0
while [ "$i" -lt 30 ]; do
  kill -0 "$PID" 2>/dev/null || { echo "--- gateway saiu apos ${i}s"; break; }
  i=$((i + 1))
  sleep 1
done

echo "--- esperando o launchd repor (ate 180s)"
i=0
while [ "$i" -lt 180 ]; do
  NOVO="$(pgrep -f 'hermes_cli.main gateway run' | head -1)"
  if [ -n "$NOVO" ] && [ "$NOVO" != "$PID" ]; then
    echo "--- reposto: pid $NOVO apos ${i}s"
    break
  fi
  i=$((i + 1))
  sleep 1
done

echo "=== depois  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
pgrep -fl 'hermes_cli.main gateway run' | cut -c1-95 || echo "(NENHUM gateway vivo — escalar ao H1)"
sed -n 's/.*"code_sha":"\([^"]*\)".*/code_sha=\1/p' /Users/farantes/.hermes/gateway_state.json
sed -n 's/.*"gateway_state":"\([a-z]*\)".*/gateway_state=\1/p' /Users/farantes/.hermes/gateway_state.json
echo "--- controle: o worker desta rodada continua vivo?"
ps -o pid=,pgid=,command= -p "$WORKER" 2>/dev/null | cut -c1-80 || echo "!!! worker $WORKER MORREU"
