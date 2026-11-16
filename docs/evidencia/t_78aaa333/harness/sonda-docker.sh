#!/bin/sh
# Roda a sonda do achado do R3 dentro do Docker, uid nao-root (regra 12).
#
# Uso: sonda-docker.sh <arvore-no-host> <rotulo>
#
# Imprime as linhas OBSERVADAS; quem compara antiga x nova e quem le.
set -eu

ARVORE="${1:?arvore no host}"
ROTULO="${2:?rotulo (ANTIGA|NOVA)}"

exec docker run --rm --network none \
  -u 502:20 \
  -v "$ARVORE":/work \
  -w /work \
  atlas-prova-t78:harness \
  sh -c 'cd /work && PYTHONPATH=/work python3 docs/evidencia/t_78aaa333/harness/sonda_janela_global.py '"$ROTULO"
