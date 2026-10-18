#!/bin/sh
# Roda a sonda do redirect sensivel dentro do Docker, uid nao-root (regra 12).
#
# Uso: redirect-docker.sh <arvore-no-host>
set -eu

ARVORE="${1:?arvore no host}"

exec docker run --rm --network none \
  -u 502:20 \
  -v "$ARVORE":/work \
  -w /work \
  atlas-prova-t78:harness \
  sh -c 'PYTHONPATH=/work python3 docs/evidencia/t_78aaa333/harness/sonda_redirect_sensivel.py'
