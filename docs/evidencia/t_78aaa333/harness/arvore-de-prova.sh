#!/bin/sh
# Copia o worktree (sem .git/venv/node_modules) para uma arvore de prova.
#
# Uso: arvore-de-prova.sh <worktree> <destino>
#
# Existe porque `git archive HEAD` so traz o COMMITADO -- util para medir a
# arvore antiga, inutil para provar o patch em curso. O destino e sempre um
# diretorio novo: o Docker monta /work gravavel e o worktree nunca e exposto.
set -eu

ORIGEM="${1:?worktree}"
DESTINO="${2:?destino (diretorio novo)}"

mkdir -p "$DESTINO"
tar -cf - -C "$ORIGEM" \
  --exclude=.git --exclude=node_modules --exclude=.venv --exclude=venv \
  --exclude=__pycache__ . | tar -x -C "$DESTINO"
echo "arvore de prova: $DESTINO"
