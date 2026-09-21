#!/bin/bash
# Sabota somente a arvore propria, preserva o rc do produtor e restaura os bytes.
set -uo pipefail
cd "$(dirname "$0")"
ACT="src/plugins/kanban/activity.ts"
TIME="src/lib/time.ts"
DRAWER="src/plugins/kanban/drawer.tsx"
VITEST="../../node_modules/.bin/vitest"
SUITE="src/lib/time.test.ts src/plugins/kanban/activity.test.ts src/plugins/kanban/drawer.test.tsx"
BK=$(mktemp -d)
cp "$ACT" "$BK/activity.ts"
cp "$TIME" "$BK/time.ts"
cp "$DRAWER" "$BK/drawer.tsx"
restaura() {
  cp "$BK/activity.ts" "$ACT"
  cp "$BK/time.ts" "$TIME"
  cp "$BK/drawer.tsx" "$DRAWER"
}
trap 'restaura; rm -rf "$BK"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
LOG_DIR=${LOG_DIR:-$(mktemp -d)}
echo "Logs integrais: $LOG_DIR"
falhas=0
roda() {
  $VITEST run $SUITE > "$LOG_DIR/$1.log" 2>&1
  local rc=$?
  grep -E 'Test Files|Tests |Duration' "$LOG_DIR/$1.log" || true
  echo "PRODUCER_EXIT=$rc"
  return "$rc"
}
mutante() {
  local nome="$1"; shift
  echo "MUTANTE: $nome"
  "$@" || { falhas=$((falhas + 1)); restaura; return; }
  if cmp -s "$ACT" "$BK/activity.ts" && cmp -s "$TIME" "$BK/time.ts" && cmp -s "$DRAWER" "$BK/drawer.tsx"; then
    echo "NAO APLICADO: $nome"
    falhas=$((falhas + 1))
    return
  fi
  roda "$nome"
  local rc=$?
  # Import/parse error sozinho nao mata mutante: precisa falhar uma assercao.
  if [ "$rc" -eq 1 ] && grep -Eq 'Tests +[1-9][0-9]* failed' "$LOG_DIR/$nome.log"; then
    echo "ACUSOU: assercao falhou, produtor rc=1"
  else
    echo "NAO COMPROVADO: veja log integral"
    falhas=$((falhas + 1))
  fi
  restaura
}
echo "=== BASELINE ==="
roda baseline || exit 2
mutante heartbeat \
  perl -0pi -e "s/new Set\(\['heartbeat', 'respawn_guarded'\]\)/new Set(['respawn_guarded'])/" "$ACT"
mutante tentativa \
  perl -0pi -e "s/const attemptStart = latestRun\?\.started_at/const attemptStart = task.started_at/" "$ACT"
mutante zero-filhos \
  perl -0pi -e "s/progress && progress\.total > 0 \?/progress ?/" "$ACT"
mutante tempo-antigo \
  perl -0pi -e "s/return parts/return [head]/" "$TIME"
mutante ausente \
  perl -0pi -e "s/return null/return '0s'/" "$ACT"
mutante erro-silencioso \
  perl -0pi -e "s/\{activityFailed && \(/{false \&\& (/" "$DRAWER"
mutante motivo \
  perl -0pi -e "s/return \{ detail: blocked \? text\(payloadOf\(blocked\), 'reason'\) : undefined, kind: 'input' \}/return { detail: blocked ? 'blocked' : undefined, kind: 'input' }/" "$ACT"
echo "=== RESTAURADO ==="
roda restaurado || exit 2
echo "MUTANTES_NAO_DETECTADOS=$falhas"
[ "$falhas" -eq 0 ]
