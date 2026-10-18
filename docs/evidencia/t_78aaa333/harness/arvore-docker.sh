#!/bin/sh
# Roda uma sonda de arvore no Docker, uid nao-root (regra 12), com a arvore
# montada SOMENTE-LEITURA. Serve as sondas que precisam comparar a instalacao
# compartilhada com o worktree deste card.
#
# Uso: arvore-docker.sh <arvore-no-host> <sonda.py> <rotulo>
set -eu

ARVORE="${1:?arvore no host}"
SONDA="${2:?arquivo da sonda}"
ROTULO="${3:?rotulo (ANTIGA|NOVA)}"
SONDA_ABS="$(cd "$(dirname "$SONDA")" && pwd)/$(basename "$SONDA")"

# Scratch do container nao-root. TMPDIR do host nao existe dentro da imagem.
_ctmp=/tmp  # no-tmp: ok — container scratch; host TMPDIR nao monta

echo "=== $ROTULO ($ARVORE) sonda=$(basename "$SONDA_ABS")"
exec docker run --rm --network none \
  -u 502:20 \
  -v "$ARVORE":/work:ro \
  -v "$SONDA_ABS":/sonda.py:ro \
  -w "$_ctmp" \
  -e HOME="$_ctmp" \
  -e PYTHONPATH=/work \
  -e PYTHONDONTWRITEBYTECODE=1 \
  atlas-prova-t78:harness \
  python3 /sonda.py
