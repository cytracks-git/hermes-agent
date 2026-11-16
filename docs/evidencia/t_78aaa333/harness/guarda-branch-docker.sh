#!/bin/sh
# Roda a suite do guarda de branch parqueada do `hermes update` contra o codigo
# da INSTALACAO compartilhada, dentro do Docker, uid nao-root, sem rede.
#
# Por que existe
# --------------
# A alternativa (a) do comentario 1141 depende de um comportamento do updater
# que NAO pode ser afirmado por leitura: com
# `updates.parked_branch_strategy: update_in_place`, uma instalacao parqueada
# numa branch recebe origin/main SEM trocar de checkout. O repositorio ja tem
# teste para isso (tests/hermes_cli/test_update_parked_branch_guard.py, que roda
# `cmd_update` real contra repositorios git reais, nao mocks) -- mas teste que
# eu nao rodei nao e prova minha.
#
# O alvo e o codigo da INSTALACAO (o que roda no relancamento do Desktop), nao o
# do worktree deste card: medir a arvore errada e falso-verde por alvo.
#
# A instalacao entra SOMENTE-LEITURA. O clone de trabalho e criado dentro do
# container e morre com ele -- nada e escrito no disco compartilhado.
#
# Uso: guarda-branch-docker.sh <sha-da-instalacao> <arquivo-de-saida>
set -eu

SHA="${1:?sha a medir na instalacao}"
SAIDA="${2:?arquivo de saida}"
INSTALACAO=/Users/farantes/.hermes/hermes-agent

[ -d "$INSTALACAO/.git" ] || { echo "NAO MEDIDO: $INSTALACAO sem .git"; exit 2; }

# Scratch do container nao-root. TMPDIR do host nao existe dentro da imagem.
_ctmp=/tmp  # no-tmp: ok — container scratch; host TMPDIR nao monta

docker run --rm --network none \
  -u 502:20 \
  --entrypoint sh \
  -v "$INSTALACAO":/instalacao:ro \
  -w "$_ctmp" \
  -e HOME="$_ctmp" \
  -e SHA="$SHA" \
  -e PYTHONDONTWRITEBYTECODE=1 \
  atlas-prova-t78:harness \
  -eu -c '
    git config --global --add safe.directory /instalacao
    git config --global user.email prova@atlas.local
    git config --global user.name "Prova t78"
    git clone -q --no-checkout --shared /instalacao /tmp/repo  # no-tmp: ok — clone morre com o container
    cd /tmp/repo  # no-tmp: ok — clone morre com o container
    git checkout -q "$SHA"
    echo "=== arvore medida: $(git rev-parse HEAD)"
    echo "=== runner canonico (nunca pytest cru)"
    scripts/run_tests.sh tests/hermes_cli/test_update_parked_branch_guard.py
  ' > "$SAIDA" 2>&1
RC=$?
echo "rc=$RC" >> "$SAIDA"
tail -20 "$SAIDA"
exit $RC
