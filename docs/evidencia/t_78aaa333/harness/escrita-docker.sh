#!/bin/sh
# Roda a sonda de custo de ESCRITA do indice dentro do Docker, uid nao-root.
#
# Uso: escrita-docker.sh <arvore-no-host> [n_eventos]
set -eu

ARVORE="${1:?arvore no host}"
EVENTOS="${2:-2000}"

exec docker run --rm --network none \
  -u 502:20 \
  -v "$ARVORE":/work \
  -w /work \
  atlas-prova-t78:harness \
  sh -c "PYTHONPATH=/work python3 docs/evidencia/t_78aaa333/harness/sonda_custo_escrita.py $EVENTOS"
