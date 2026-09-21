#!/bin/sh
# Roda a sonda do ORFAO (status waiting_approval) numa arvore, no Docker, uid
# nao-root (regra 12). A sonda precisa de DUAS arvores para ter significado:
#
#   ANTIGA = instalacao compartilhada ~/.hermes/hermes-agent (sem o patch)
#   NOVA   = worktree deste card (com o patch)
#
# As duas sao montadas SOMENTE-LEITURA: e a arvore REAL que se quer medir, nao
# uma reconstrucao, e nada do host pode ser escrito pela sonda. O banco de
# prova nasce em /tmp DENTRO do container e morre com ele.
#
# Uso: orfao-docker.sh <arvore-no-host> <rotulo>
set -eu

ARVORE="${1:?arvore no host}"
ROTULO="${2:?rotulo (ANTIGA|NOVA)}"
SONDA="$(cd "$(dirname "$0")" && pwd)/sonda_status_desconhecido.py"

echo "=== $ROTULO ($ARVORE)"
exec docker run --rm --network none \
  -u 502:20 \
  -v "$ARVORE":/work:ro \
  -v "$SONDA":/sonda.py:ro \
  -w /tmp \
  -e HOME=/tmp \
  -e PYTHONPATH=/work \
  -e PYTHONDONTWRITEBYTECODE=1 \
  atlas-prova-t78:harness \
  python3 /sonda.py
