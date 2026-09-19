#!/bin/bash
# MUTANTE da rodada 3: a versao VELHA morre contra os testes novos?
#
# Testes novos passando no codigo novo nao provam nada sozinhos — podem estar
# medindo o que ja funcionava. A pergunta e: o codigo ANTERIOR (commit
# 3389414eb43, que o revisor reprovou) FALHA nestes mesmos testes?
#
# Se a versao velha passar, o teste esta desligado e o "conserto" e decorativo.
#
# CUIDADO QUE ESTE SCRIPT JA CUSTOU CARO: a primeira versao restaurava com
# `git checkout -- <alvos>`, que joga fora alteracoes NAO COMMITADAS. Rodando
# com o conserto ainda no working tree, ela APAGOU o conserto inteiro. Agora a
# restauracao e por COPIA FISICA do working tree, que nao depende do git nem de
# o trabalho estar commitado.
set -u
cd /Users/farantes/atlas/wt/t7e6fb387-direto || exit 1

ALVOS="hermes_cli/kanban_db.py hermes_cli/kanban_db_workspace.py"
TESTE="tests/hermes_cli/test_kanban_evidence_gate_round3.py"
VELHO="3389414eb43"   # HEAD da rodada 2, reprovado pelo revisor

BACKUP=$(mktemp -d "${TMPDIR:-/tmp}/mutante-r3-XXXXXX")
for f in $ALVOS; do
  mkdir -p "$BACKUP/$(dirname "$f")"
  cp -p "$f" "$BACKUP/$f" || { echo "backup falhou para $f"; exit 1; }
done
echo "working tree salvo em $BACKUP"

restaurar() {
  echo
  echo "--- restaurando o working tree a partir da COPIA ---"
  for f in $ALVOS; do
    cp -p "$BACKUP/$f" "$f"
  done
  # Prova de que a restauracao funcionou: o conserto tem de estar de volta.
  local n
  n=$(grep -c "_descobrir_repos_aninhados" hermes_cli/kanban_db.py 2>/dev/null)
  echo "marcador do conserto em kanban_db.py: $n ocorrencia(s) (0 = RESTAURACAO FALHOU)"
}
trap restaurar EXIT

echo "======================================================================"
echo "MUTANTE: codigo da RODADA 2 ($VELHO) contra os testes da RODADA 3"
echo "======================================================================"
echo "Esperado: FALHAR. Um teste que passa no codigo velho nao mede o conserto."
echo

for f in $ALVOS; do
  git show "$VELHO:$f" > "$f" || { echo "nao consegui materializar $f"; exit 1; }
done

env -u HERMES_DELEGATED_CHILD_CONTEXT .venv/bin/python -m pytest "$TESTE" \
  -q --no-header -p no:randomly --tb=no 2>&1 | grep -E "^(FAILED|ERROR)|passed|failed"

echo
echo "======================================================================"
echo "Leia acima: os casos que FALHARAM sao os que o conserto de fato matou."
echo "======================================================================"

