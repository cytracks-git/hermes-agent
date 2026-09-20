#!/bin/sh
# Suites que so existem no candidato (card t_78aaa333), pelo runner canonico.
# Rodam a parte de proposito: nao tem contraparte no baseline, entao nao entram
# na comparacao -- mas tambem nao somem do relatorio.
set -u
SAIDA="${1:-/tmp/prova-t78}"
mkdir -p "$SAIDA"

CT=prova-novos-$$
docker run --name "$CT" \
  -v /Users/farantes/atlas/wt/kanban-aprovacao-interativa:/src:ro \
  -v "$SAIDA":/saida \
  --entrypoint sh atlas-prova-t78:harness -c '
set -e
cp -a /src /work
H=/work/docs/evidencia/t_78aaa333/harness
sh "$H/prova.sh" /work "$H/alvos-novos.txt" /saida candidato-novos
'
rc=$?
docker rm "$CT" >/dev/null 2>&1
echo "docker rc=$rc"
exit $rc
