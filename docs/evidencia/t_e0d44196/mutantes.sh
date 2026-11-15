#!/usr/bin/env bash
# Mutantes do C2 (t_e0d44196): cada sabotagem tem de reprovar o teste focal.
# Uso: bash mutantes.sh <worktree>. Restaura os arquivos ao fim de cada mutante.
set -u
WT="$1"; cd "$WT" || exit 2
T=tests/hermes_cli/test_kanban_transient_redispatch.py
F=hermes_cli/kanban_db_transient.py
D=hermes_cli/kanban_db_dispatch.py
run() {
  local nome="$1" arq="$2" de="$3" para="$4" todos="${5:-}"
  cp "$arq" "$arq.bak"
  python3 - "$arq" "$de" "$para" "$todos" <<'PY'
import sys; p,a,b,t=sys.argv[1:]; s=open(p).read(); assert a in s, a; open(p,"w").write(s.replace(a,b) if t else s.replace(a,b,1))
PY
  if scripts/run_tests.sh "$T" >/tmp/mut.$$ 2>&1; then echo "SOBREVIVEU $nome"; else echo "morto $nome"; fi
  mv "$arq.bak" "$arq"
}
# M1 base antiga: varredura nao ligada ao tick (comportamento pre-C2)
run sem_wiring "$D" "result.transient_redispatched = redispatch_transient_blocks(" "result.transient_redispatched = [] or (lambda **k: [])("
# M2 ignora o atraso (despacha o fresco tambem)
run sem_atraso "$F" "if now - int(last[\"created_at\"] or 0) < delay_seconds:" "if False:"
# M3 aceita qualquer kind (destrava needs_input): tira o filtro do SELECT e do CAS
run qualquer_kind "$F" "AND block_kind = 'transient' " "" all
# M4 zera o disjuntor de recorrencia ao retomar (loop infinito)
run zera_recorrencia "$F" "\"UPDATE tasks SET status = ? WHERE id = ? AND status = 'blocked' \"" "\"UPDATE tasks SET status = ?, block_kind = NULL, block_recurrences = 0 WHERE id = ? AND status = 'blocked' \""
# M5 ignora config 0 (sempre liga)
run ignora_off "$F" "return value if value > 0 else 0" "return value if value > 0 else 600"
# M6 destrava card parado pelo disjuntor (classified_in_place)
run destrava_breaker "$F" "if _kb._json_dict(last[\"payload\"]).get(\"classified_in_place\"):" "if False:"
# M7 ignora o limite de falhas do breaker
run ignora_failure_limit "$F" "if int(row[\"consecutive_failures\"] or 0) >= limit:" "if False:"
rm -f /tmp/mut.$$
