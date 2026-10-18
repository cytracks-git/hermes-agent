#!/bin/sh
# Segundo degrau da recarga: SIGTERM ao gateway que drenou mas nao saiu.
#
# Contexto medido nesta rodada
# ----------------------------
# SIGUSR1 fez o caminho inteiro do desligamento: "Shutdown phase: drain done
# at +0.00s ... Gateway stopped (total teardown 0.15s)", gateway_state.json
# virou state=stopped / restart_requested=true. O PROCESSO, porem, continuou
# vivo: `sample 31800` mostra a main thread parada em ``kevent`` dentro do
# loop asyncio, e nenhuma linha nova em gateway-exit-diag.log -- ou seja, o
# ``_hard_exit_after_gateway_teardown`` nunca foi alcancado.
#
# SIGTERM e o degrau seguinte porque o proprio Hermes o instala como saida
# limpa (hermes_cli/gateway.py: SIGTERM -> sys.exit(128+signum)), o que cai no
# ``except SystemExit`` que chama a saida dura por os._exit. Nao se escala para
# SIGKILL aqui: com approval_requests=0 e active_agents=0 nao ha trabalho vivo
# a perder, mas -9 nao e autorizado por conta propria neste card.
#
# Uso: sigterm-gateway.sh <pid> [segundos]
set -eu

PID="${1:?pid}"
ESPERA="${2:-60}"

echo "=== SIGTERM em $PID  $(date -u +%Y-%m-%dT%H:%M:%SZ)"
kill -TERM "$PID"

i=0
while [ "$i" -lt "$ESPERA" ]; do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "--- saiu apos ${i}s"
    break
  fi
  i=$((i + 1))
  sleep 1
done

if kill -0 "$PID" 2>/dev/null; then
  echo "!!! $PID AINDA VIVO apos ${ESPERA}s — parar aqui e relatar; NAO usar SIGKILL sem H1"
  ps -o pid=,stat=,command= -p "$PID" | cut -c1-100
  exit 1
fi

echo "--- esperando o supervisor launchd repor"
i=0
while [ "$i" -lt 120 ]; do
  NOVO="$(pgrep -f 'hermes_cli.main gateway run' | head -1)"
  if [ -n "$NOVO" ]; then
    echo "--- reposto: pid $NOVO"
    break
  fi
  i=$((i + 1))
  sleep 1
done

echo "=== estado final"
pgrep -fl 'hermes_cli.main gateway run' | cut -c1-90 || echo "(nenhum gateway vivo)"
sed -n 's/.*"code_sha":"\([^"]*\)".*/code_sha=\1/p' /Users/farantes/.hermes/gateway_state.json
echo "--- worker deste card (nao pode ter morrido):"
ps -o pid=,pgid=,command= -p 56467 2>/dev/null | cut -c1-80 || echo "!!! worker 56467 sumiu"
