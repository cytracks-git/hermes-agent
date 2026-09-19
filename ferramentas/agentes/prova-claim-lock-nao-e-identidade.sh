#!/usr/bin/env bash
# Prova em Docker NAO-ROOT de que `claim_lock` nao decide autoria.
#
# Por que nao-root: o container roda como uid 0 por padrao, e root atravessa
# permissao de diretorio -- uma bateria que so passa como root pode estar
# aprovando por construcao. Aqui o -u "$(id -u):$(id -g)" e obrigatorio.
#
# Rodadas, nesta ordem (nenhuma sozinha prova nada):
#   VERDE     bateria contra a arvore consertada
#   MUTANTE   a leitura ERRADA (identidade = claim_lock) reintroduzida no codigo;
#             a bateria TEM de reprovar, ou o sensor nao discrimina
#   RESTAURA  mutante desfeito e VERDE de novo, provando que nada ficou sujo
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGEM="atlas-claimlock-lab:2"   # python:3.13-slim + pytest + deps (ver Dockerfile ao lado)
ALVO="tests/hermes_cli/test_kanban_claim_lock_nao_e_identidade.py"
FONTE="hermes_cli/kanban_db.py"
PISO=8   # testes que TEM de ser coletados; menos que isso e cegueira, nao aprovacao

cd "$REPO" || exit 2

rodar() {
  # Sem pipe no rc: `cmd | tail` devolve o status do TAIL, e a rodada verde
  # passava com 8 erros de import. O mutante pegou esse defeito do medidor.
  local saida rc coletados
  saida="$(docker run --rm -u "$(id -u):$(id -g)" -e HOME=/tmp \
    -v "$REPO":/src -w /src "$IMAGEM" \
    python -m pytest -q --no-header -p no:cacheprovider --log-cli-level=CRITICAL "$ALVO" 2>&1)"
  rc=$?
  printf '%s\n' "$saida" | grep -v '^INFO' | tail -12
  # PISO: verde com poucos testes coletados e cegueira (import quebrado,
  # arquivo renomeado, filtro errado), nunca aprovacao.
  coletados="$(printf '%s\n' "$saida" | grep -Eo '[0-9]+ (passed|failed)' \
               | grep -Eo '^[0-9]+' | awk '{s+=$1} END {print s+0}')"
  echo "   (testes contabilizados: ${coletados}, piso ${PISO})"
  if [ "$coletados" -lt "$PISO" ]; then
    echo "   NAO MEDIDO: abaixo do piso de coleta"
    return 99
  fi
  return $rc
}

echo "== 0. IDENTIDADE DO PROCESSO NO CONTAINER (tem de ser nao-root) =="
docker run --rm -u "$(id -u):$(id -g)" "$IMAGEM" id
echo

echo "== 1. VERDE: arvore consertada =="
rodar; verde=$?
echo "rc=$verde"
echo

echo "== 2. MUTANTE: reintroduzir 'identidade = claim_lock' =="
BACKUP="$(mktemp)"; cp "$FONTE" "$BACKUP"
restaura() { cp "$BACKUP" "$FONTE"; rm -f "$BACKUP"; }
trap restaura EXIT

# A mutacao E o defeito historico: decidir autorrevisao comparando o lock de
# despacho dos dois runs, em vez do run. Como os dois compartilham o lock do
# gateway, isso responde "sou eu" sempre.
python3 - "$FONTE" <<'PY'
import sys
caminho = sys.argv[1]
fonte = open(caminho, encoding="utf-8").read()
alvo = '    is_self_review = (author["run_id"] == myself["run_id"]) if (author and myself) else None'
mutante = (
    '    _la = conn.execute("SELECT claim_lock FROM task_runs WHERE id = ?",\n'
    '                       (author["run_id"],)).fetchone()["claim_lock"] if author else None\n'
    '    _ls = conn.execute("SELECT claim_lock FROM task_runs WHERE id = ?",\n'
    '                       (myself["run_id"],)).fetchone()["claim_lock"] if myself else None\n'
    '    is_self_review = (_la == _ls) if (author and myself) else None'
)
if alvo not in fonte:
    print("MUTANTE NAO APLICADO: ancora ausente", file=sys.stderr)
    raise SystemExit(3)
open(caminho, "w", encoding="utf-8").write(fonte.replace(alvo, mutante, 1))
PY
aplicou=$?
if [ $aplicou -ne 0 ]; then
  echo "NAO MEDIDO: mutante nao entrou no arquivo; nada a concluir"; exit 3
fi
if diff -q "$BACKUP" "$FONTE" >/dev/null; then
  echo "NAO MEDIDO: arquivo identico apos mutar; nada a concluir"; exit 3
fi
echo "(mutante confirmado no arquivo: diff acusa diferenca)"
rodar; mutado=$?
echo "rc=$mutado"
echo

echo "== 3. RESTAURA e VERDE de novo =="
restaura; trap - EXIT
rodar; verde2=$?
echo "rc=$verde2"
echo

echo "== VEREDITO =="
if [ $verde -eq 0 ] && [ $mutado -ne 0 ] && [ $verde2 -eq 0 ]; then
  echo "OK: verde=$verde mutante=$mutado(reprovou) restaurado=$verde2 -- o sensor DISCRIMINA."
  exit 0
fi
echo "FALHOU: verde=$verde mutante=$mutado restaurado=$verde2"
[ $mutado -eq 0 ] && echo "  -> o mutante PASSOU: a bateria nao mede o defeito que diz medir."
exit 1
