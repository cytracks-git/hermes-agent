#!/bin/sh
# Mede, em container descartavel, se o merge de origin/main DENTRO da branch
# deste card conflita -- e onde. Nada e escrito na instalacao compartilhada.
#
# Por que existe
# --------------
# A alternativa (a) do comentario 1141 ("fixar a instalacao no branch do card")
# so e executavel se o mecanismo NATIVO do updater
# (updates.parked_branch_strategy: update_in_place) conseguir trazer origin/main
# para dentro da branch. O proprio updater documenta que "a conflict stops the
# update cleanly" -- ou seja, conflito nao quebra nada, mas DEIXA A INSTALACAO
# PARADA no codigo do card, 1674 commits atras. Isso muda a decisao, entao tem
# de ser medido ANTES de tocar em qualquer coisa, nao descoberto na janela.
#
# Metodo, e por que cada parte esta aqui:
#   - a instalacao e montada SOMENTE-LEITURA; o clone vive dentro do container
#   - uid 502:20 (nao-root): root ignora permissao e aprova por construcao
#   - --network none: o merge e 100% local; se algo tentar rede, falha visivel
#   - CONTROLE POSITIVO: um merge que SABIDAMENTE conflita (a propria main
#     contra uma alteracao fabricada no mesmo arquivo) tem de sair com rc!=0.
#     Sem ele, "merge limpo" pode ser um script que nao mediu nada.
#
# Uso: merge-conflito-docker.sh <sha-da-branch-do-card> <sha-do-alvo>
set -eu

CARD_SHA="${1:?sha da branch do card}"
ALVO_SHA="${2:?sha do alvo (main)}"
INSTALACAO=/Users/farantes/.hermes/hermes-agent

[ -d "$INSTALACAO/.git" ] || { echo "NAO MEDIDO: $INSTALACAO sem .git"; exit 2; }

exec docker run --rm --network none \
  -u 502:20 \
  --entrypoint sh \
  -v "$INSTALACAO":/instalacao:ro \
  -w /tmp \
  -e HOME=/tmp \
  -e CARD_SHA="$CARD_SHA" \
  -e ALVO_SHA="$ALVO_SHA" \
  alpine/git:latest \
  -eu -c '
    git config --global user.email prova@atlas.local
    git config --global user.name "Prova t78"
    git config --global --add safe.directory /instalacao

    echo "=== clonando a instalacao (somente leitura na origem)"
    # --shared: os objetos ficam na instalacao (montada :ro, so leitura); o que
    # este teste escrever vai para /tmp/repo e morre com o container.
    git clone -q --no-checkout --shared /instalacao /tmp/repo
    cd /tmp/repo
    # Os SHAs ja estao no banco de objetos compartilhado: nada de fetch por ref
    # abreviada (que falha por nao ser um ref, e mascarava a medicao).
    git rev-parse --verify --quiet "${CARD_SHA}^{commit}" >/dev/null || { echo "NAO MEDIDO: $CARD_SHA ausente"; exit 2; }
    git rev-parse --verify --quiet "${ALVO_SHA}^{commit}" >/dev/null || { echo "NAO MEDIDO: $ALVO_SHA ausente"; exit 2; }
    git tag card "$CARD_SHA"
    git tag alvo "$ALVO_SHA"

    echo "=== base comum"
    BASE=$(git merge-base card alvo)
    echo "base=$BASE"
    echo "commits do alvo ausentes no card: $(git rev-list --count card..alvo)"
    echo "commits do card ausentes no alvo: $(git rev-list --count alvo..card)"

    echo
    echo "=== MEDICAO: merge de alvo DENTRO do card (merge-tree, sem checkout)"
    set +e
    SAIDA=$(git merge-tree --write-tree card alvo 2>&1)
    RC=$?
    set -e
    echo "rc=$RC"
    if [ "$RC" -eq 0 ]; then
      echo "VEREDITO: MERGE LIMPO — nenhum conflito entre o card e o alvo"
    else
      echo "VEREDITO: CONFLITO"
      echo "$SAIDA" | sed -n "1,60p"
    fi

    echo
    echo "=== CONTROLE POSITIVO: um conflito fabricado TEM de acusar"
    git checkout -q -b pos card
    ARQ=$(git diff --name-only "$BASE" alvo | grep -E "\.py$" | head -1)
    echo "arquivo escolhido (a main mexeu nele): $ARQ"
    printf "# sabotagem do controle positivo\n" > "$ARQ"
    git commit -q -am "sabotagem"
    set +e
    git merge-tree --write-tree pos alvo >/dev/null 2>&1
    RCPOS=$?
    set -e
    echo "rc do controle positivo=$RCPOS"
    if [ "$RCPOS" -eq 0 ]; then
      echo "CONTROLE POSITIVO FALHOU: o medidor nao acusa nem conflito fabricado — DESCARTAR a medicao acima"
      exit 2
    fi
    echo "CONTROLE POSITIVO OK: o medidor acusa conflito quando ele existe"
  '
