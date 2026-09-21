#!/bin/sh
# Recarga DRAIN-AWARE do gateway, com readback por PROCESSO (rodada 1060).
#
# Por que assim
# -------------
# O gateway e supervisionado por launchd (ai.hermes.gateway, via o shim
# hermes_cli.stderr_timestamp). SIGUSR1 e mapeado por gateway/run.py para
# ``request_restart(via_service=True)``: recusa turnos novos, drena o que esta
# em voo, chama stop() e sai; o supervisor repoe o processo ja no codigo novo.
# Nao se usa SIGKILL: matar pool a -9 ja custou trabalho verde virando vermelho.
#
# Os workers Kanban NAO sao derrubados por isso: o dispatcher os cria com
# ``start_new_session=True`` (sessao e process group proprios), entao o sinal
# ao gateway nao se propaga a eles. Medido nesta rodada: pgid 56467 e 63113,
# ambos distintos do 31796 do gateway.
#
# Uso: recarrega-gateway.sh <pid-do-gateway> [segundos-de-espera]
set -eu

PID="${1:?pid do gateway}"
ESPERA="${2:-180}"
ESTADO=/Users/farantes/.hermes/gateway_state.json

sha_do_estado() {
  sed -n 's/.*"code_sha":"\([^"]*\)".*/\1/p' "$ESTADO" 2>/dev/null
}
pid_do_estado() {
  sed -n 's/.*"pid":\([0-9]*\).*/\1/p' "$ESTADO" 2>/dev/null
}

echo "=== ANTES  pid_arquivo=$(pid_do_estado) code_sha=$(sha_do_estado)"
echo "--- workers vivos antes (nao podem morrer):"
ps -o pid=,pgid=,command= -p 56467 -p 63113 2>/dev/null | cut -c1-90 || true

echo "--- enviando SIGUSR1 ao $PID (drain-aware)"
kill -USR1 "$PID"

i=0
while [ "$i" -lt "$ESPERA" ]; do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "--- gateway $PID saiu apos ${i}s (drenagem concluida)"
    break
  fi
  i=$((i + 1))
  sleep 1
done
if kill -0 "$PID" 2>/dev/null; then
  echo "!!! gateway $PID AINDA VIVO apos ${ESPERA}s — NAO escalar para SIGKILL; relatar e parar"
  exit 1
fi

echo "--- esperando o supervisor repor"
i=0
while [ "$i" -lt 120 ]; do
  NOVO="$(pid_do_estado)"
  if [ -n "$NOVO" ] && [ "$NOVO" != "$PID" ] && kill -0 "$NOVO" 2>/dev/null; then
    echo "--- reposto: pid $NOVO"
    break
  fi
  i=$((i + 1))
  sleep 1
done

echo "=== DEPOIS pid_arquivo=$(pid_do_estado) code_sha=$(sha_do_estado)"
echo "--- workers vivos depois (controle: os MESMOS pids de antes):"
ps -o pid=,pgid=,command= -p 56467 -p 63113 2>/dev/null | cut -c1-90 || echo "!!! worker sumiu"
