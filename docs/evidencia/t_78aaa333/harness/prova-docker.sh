#!/bin/sh
# Executa o runner canonico dentro do Docker para o card t_78aaa333.
#
# Uso: prova-docker.sh <arvore-no-host> <dir-saida-no-host> <lista-de-alvos> <rotulo>
#
# A arvore entra em /work GRAVAVEL de proposito: o runner paralelo escreve
# arquivos temporarios, e o controle negativo precisa sabotar e restaurar. A
# arvore passada e sempre uma COPIA (git archive), nunca o worktree.
#
# uid/gid 502:20 = o mesmo usuario nao-root do host, exigencia da regra 12.
set -eu

ARVORE="${1:?arvore no host}"
SAIDA="${2:?dir de saida no host}"
ALVOS="${3:?lista de alvos, caminho relativo a arvore}"
ROTULO="${4:?rotulo}"

mkdir -p "$SAIDA"

exec docker run --rm --network none \
  -u 502:20 \
  -v "$ARVORE":/work \
  -v "$SAIDA":/saida \
  -w /work \
  atlas-prova-t78:harness \
  sh docs/evidencia/t_78aaa333/harness/prova.sh /work "$ALVOS" /saida "$ROTULO"
