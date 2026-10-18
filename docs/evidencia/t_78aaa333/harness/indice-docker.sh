#!/bin/sh
# Roda a sonda do indice candidato dentro do Docker, uid nao-root (regra 12).
#
# Uso: indice-docker.sh <arvore-no-host> [n_linhas] [n_leituras]
set -eu

ARVORE="${1:?arvore no host}"
LINHAS="${2:-1400}"
LEITURAS="${3:-200}"
POSICAO="${4:-fim}"

exec docker run --rm --network none \
  -u 502:20 \
  -v "$ARVORE":/work \
  -w /work \
  atlas-prova-t78:harness \
  sh -c "PYTHONPATH=/work python3 docs/evidencia/t_78aaa333/harness/sonda_indice_candidato.py $LINHAS $LEITURAS $POSICAO"
