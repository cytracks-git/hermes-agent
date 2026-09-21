#!/bin/sh
# Snapshot ANTES/DEPOIS do rebuild+swap do bundle Desktop (rodada C28, card t_78aaa333).
#
# Irmao do snapshot-instalacao.sh: le, nao escreve. O MESMO instrumento roda nos
# dois lados da janela, para que a comparacao seja entre saidas iguais e nao
# entre dois comandos parecidos digitados em momentos diferentes.
#
# A pergunta que ele responde e uma so: QUAL BUNDLE o processo que o operador ve
# esta carregando -- nao "o que existe no disco". Por isso mede hash do asar,
# marcador dentro do asar, e os pids com lstart; leitura de fonte nao entra.
#
# Uso: snapshot-desktop.sh <ANTES|DEPOIS>
set -eu

ROTULO="${1:?rotulo (ANTES|DEPOIS)}"
INST=/Users/farantes/.hermes/hermes-agent
APP="$INST/apps/desktop/release/mac-arm64/Hermes.app"
ASAR="$APP/Contents/Resources/app.asar"
UNPACKED="$APP/Contents/Resources/app.asar.unpacked"

echo "=== SNAPSHOT DESKTOP $ROTULO  $(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "--- instalacao"
git -C "$INST" rev-parse HEAD
git -C "$INST" log --oneline -1

echo "--- app.asar (bytes, nao fonte)"
if [ -f "$ASAR" ]; then
  ls -l "$ASAR" | awk '{print "tamanho="$5"  mtime="$6" "$7" "$8}'
  echo "sha256=$(shasum -a 256 "$ASAR" | cut -d' ' -f1)"
  # grep -c ja IMPRIME 0 quando nao acha, e sai com rc=1. Um `|| echo 0` aqui
  # imprimiria o zero DUAS vezes (foi o que aconteceu no primeiro snapshot);
  # o `|| true` preserva o unico zero e so impede o set -e de derrubar tudo.
  for MARCA in waiting_approval retryApprovalNotice notice-retry; do
    echo "marcador $MARCA=$(grep -a -c "$MARCA" "$ASAR" || true)"
  done
else
  echo "(app.asar AUSENTE em $ASAR)"
fi

echo "--- app.asar.unpacked/dist (o dist real que o renderer carrega)"
if [ -d "$UNPACKED/dist" ]; then
  echo "arquivos=$(find "$UNPACKED/dist" -type f | wc -l | tr -d ' ')"
  echo "marcador waiting_approval=$(grep -a -r -l waiting_approval "$UNPACKED/dist" 2>/dev/null | wc -l | tr -d ' ') arquivo(s)"
else
  echo "(sem app.asar.unpacked/dist)"
fi

echo "--- build stamp (perfil default: e onde o Desktop do operador roda)"
cat /Users/farantes/.hermes/desktop-build-stamp.json 2>/dev/null || echo "(ausente)"

echo "--- processos do Desktop (pid + lstart: idade e o que separa bundle novo de velho)"
ps -eo pid,lstart,command | grep -F "$APP/Contents/MacOS/Hermes" | grep -v grep | cut -c1-140 || echo "(Hermes.app nao esta rodando)"
echo "--- backend serve (filho do app)"
ps -eo pid,ppid,lstart,command | grep -E "hermes_cli.main .*serve" | grep -v grep | cut -c1-160 || echo "(sem backend serve)"

echo "--- gateway (processo separado; nao deve mudar nesta janela)"
cat /Users/farantes/.hermes/gateway_state.json 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" ".join(f"{k}={d.get(k)}" for k in ("pid","gateway_state","code_sha","code_version")))' 2>/dev/null || echo "(sem gateway_state)"

echo "=== FIM DESKTOP $ROTULO"
