#!/bin/bash
# MUTANTE da rodada 2: testes NOVOS contra o codigo VELHO.
#
# Monta uma arvore onde hermes_cli/kanban_db.py e tools/kanban_tools.py voltam
# a versao ANTERIOR (HEAD~, o gate da rodada 1) mas os TESTES sao os novos.
# Se o codigo velho passar, o teste nao mede a classe do defeito — ele so
# descreve o caso particular que eu ja sabia consertar.
set -uo pipefail

WT=/Users/farantes/atlas/wt/t7e6fb387-direto
VELHO=93d8e373ecd          # rodada 1: refs locais como autoridade, except: pass
LAB=/tmp/mutante-r2
PY="$WT/.venv/bin/python"

rm -rf "$LAB"; mkdir -p "$LAB"
cd "$WT" || exit 1

# Arvore de trabalho = HEAD (testes novos), com os DOIS arquivos de producao
# revertidos para a versao velha.
git archive HEAD | tar -x -C "$LAB"
git show "$VELHO:hermes_cli/kanban_db.py"  > "$LAB/hermes_cli/kanban_db.py"
git show "$VELHO:tools/kanban_tools.py"    > "$LAB/tools/kanban_tools.py"

ln -s "$WT/.venv" "$LAB/.venv" 2>/dev/null

cd "$LAB" || exit 1
echo "=== MUTANTE: codigo de $VELHO + testes de HEAD ==="
"$PY" -m pytest \
  tests/hermes_cli/test_kanban_evidence_gate_round2.py \
  -q -p no:logging --no-header 2>&1 | grep -vE "^(INFO|DEBUG|WARNING)" | tail -15
