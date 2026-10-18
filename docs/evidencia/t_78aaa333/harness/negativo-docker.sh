#!/bin/sh
# Roda o controle negativo do recorte 1057 dentro do Docker, uid nao-root.
#
# Uso: negativo-docker.sh <arvore-no-host> <dir-saida-no-host>
#
# A arvore entra GRAVAVEL porque a sabotagem edita o arquivo e o restaura --
# por isso ela e sempre uma COPIA, nunca o worktree.
set -eu

ARVORE="${1:?arvore no host}"
SAIDA="${2:?dir de saida no host}"

mkdir -p "$SAIDA"

exec docker run --rm --network none \
  -u 502:20 \
  -v "$ARVORE":/work \
  -v "$SAIDA":/saida \
  -w /work \
  atlas-prova-t78:harness \
  sh -c 'PYTHONPATH=/work python3 docs/evidencia/t_78aaa333/harness/controle_negativo_1057.py'
