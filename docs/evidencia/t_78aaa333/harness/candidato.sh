#!/bin/sh
# Executa prova.sh dentro do container sobre a arvore CANDIDATA (regra 12).
#
# O worktree entra somente-leitura em /src e e copiado para /work porque o
# runner canonico escreve (cache, __pycache__, artefatos de sessao).
#
# RC: o `docker run` propaga o exit code do prova.sh, que por sua vez propaga o
# do runner. Sem pipes em lugar nenhum da cadeia.
#
# Uso: candidato.sh <dir-de-saida-no-host>
set -u
SAIDA="${1:-/tmp/prova-t78}"
mkdir -p "$SAIDA"

CT=prova-cand-$$
docker run --name "$CT" \
  -v /Users/farantes/atlas/wt/kanban-aprovacao-interativa:/src:ro \
  -v "$SAIDA":/saida \
  --entrypoint sh atlas-prova-t78:harness -c '
set -e
cp -a /src /work
H=/work/docs/evidencia/t_78aaa333/harness
sh "$H/prova.sh" /work "$H/alvos-comuns.txt" /saida candidato-comuns
'
rc=$?
docker rm "$CT" >/dev/null 2>&1
echo "docker rc=$rc"
exit $rc
