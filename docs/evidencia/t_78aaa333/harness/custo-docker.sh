#!/bin/sh
# Roda a sonda de custo de leitura dentro do Docker, uid nao-root (regra 12).
#
# Uso: custo-docker.sh <arvore-no-host> [n_linhas] [n_leituras]
set -eu

ARVORE="${1:?arvore no host}"
LINHAS="${2:-5000}"
LEITURAS="${3:-200}"

exec docker run --rm --network none \
  -u 502:20 \
  -v "$ARVORE":/work \
  -w /work \
  atlas-prova-t78:harness \
  sh -c "PYTHONPATH=/work python3 docs/evidencia/t_78aaa333/harness/sonda_custo_leitura.py $LINHAS $LEITURAS"
