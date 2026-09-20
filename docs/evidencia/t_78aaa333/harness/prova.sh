#!/bin/sh
# Prova de suite do card t_78aaa333, pelo runner CANONICO, com RC REAL.
#
# Por que este script existe
# --------------------------
# H1 apontou tres defeitos no ciclo anterior, e cada um vira uma regra aqui:
#
#   1. `pytest | grep | tail` mascara o exit code -- o rc lido era o do `tail`.
#      AQUI: a saida vai para ARQUIVO por redirecionamento, o rc e capturado
#      imediatamente em `$?`, e NADA e canalizado por pipe.
#   2. baseline e candidato rodaram alvos diferentes -- isso nao e controle.
#      AQUI: a lista de alvos e um ARQUIVO passado por parametro, o mesmo para
#      os dois lados; o script recusa rodar sem ele.
#   3. `pytest` cru nao e aceite. AQUI: sempre `scripts/run_tests.sh`.
#
# `--tb=no -rf` e obrigatorio: o runner paralelo corta a saida de cada arquivo
# nas ultimas ~30 linhas, e com traceback longo as linhas FAILED se perdem --
# a comparacao por ID ficaria cega sem barulho nenhum.
#
# Uso:
#   prova.sh <arvore> <lista-de-alvos> <dir-de-saida> <rotulo>
#
# Saida (em <dir-de-saida>):
#   <rotulo>.log   saida completa do runner
#   <rotulo>.rc    exit code REAL do runner
#   <rotulo>.ids   ids de teste que falharam, um por linha, ordenados
set -u

ARVORE="${1:?arvore do codigo (ex: /src)}"
ALVOS="${2:?arquivo com a lista de alvos, um por linha}"
SAIDA="${3:?diretorio de saida}"
ROTULO="${4:?rotulo (baseline|candidato|novos)}"

[ -d "$ARVORE" ] || { echo "arvore inexistente: $ARVORE" >&2; exit 2; }
[ -s "$ALVOS" ]  || { echo "lista de alvos vazia ou inexistente: $ALVOS" >&2; exit 2; }

mkdir -p "$SAIDA"
LOG="$SAIDA/$ROTULO.log"
RC="$SAIDA/$ROTULO.rc"
IDS="$SAIDA/$ROTULO.ids"

# Alvos que nao existem NESTA arvore sao erro de protocolo, nao detalhe: seguir
# em frente compararia conjuntos diferentes outra vez.
FALTANDO=""
while IFS= read -r alvo; do
  case "$alvo" in ''|\#*) continue ;; esac
  [ -f "$ARVORE/$alvo" ] || FALTANDO="$FALTANDO $alvo"
done < "$ALVOS"
if [ -n "$FALTANDO" ]; then
  echo "ALVOS AUSENTES em $ARVORE:$FALTANDO" >&2
  echo "   (lista de alvos e candidato/baseline tem de casar -- corrija a lista)" >&2
  exit 2
fi

LISTA=""
while IFS= read -r alvo; do
  case "$alvo" in ''|\#*) continue ;; esac
  LISTA="$LISTA $alvo"
done < "$ALVOS"

cd "$ARVORE" || exit 2

# Sem pipe: redirecionamento puro, rc capturado na linha seguinte.
# `bash` explicito: run_tests.sh e um script bash (usa BASH_SOURCE e arrays) e
# o `sh` da imagem e dash -- invocar por `sh` morre em "Bad substitution".
bash scripts/run_tests.sh $LISTA --tb=no -rf -q > "$LOG" 2>&1
rc=$?
echo "$rc" > "$RC"

# Os ids saem do ARQUIVO ja gravado -- extrair aqui nao altera o rc acima.
grep -hoE '^FAILED [^ ]+' "$LOG" 2>/dev/null | sed 's/^FAILED //' | sort -u > "$IDS"

echo "rotulo=$ROTULO rc=$rc falhas=$(wc -l < "$IDS" | tr -d ' ') log=$LOG"
exit "$rc"
