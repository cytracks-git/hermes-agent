#!/bin/sh
# Controle negativo pelo runner canonico, dentro do container (regra 12).
# Uso: negativo.sh <dir-de-saida-no-host>
set -u
SAIDA="${1:-/tmp/prova-t78}"
mkdir -p "$SAIDA"

CT=prova-neg-$$
docker run --name "$CT" \
  -v /Users/farantes/atlas/wt/kanban-aprovacao-interativa:/src:ro \
  -v "$SAIDA":/saida \
  --entrypoint sh atlas-prova-t78:harness -c '
set -e
cp -a /src /work
python3 /work/docs/evidencia/t_78aaa333/harness/controle_negativo.py
'
rc=$?
docker rm "$CT" >/dev/null 2>&1
echo "docker rc=$rc"
exit $rc
