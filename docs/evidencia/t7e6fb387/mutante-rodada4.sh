#!/usr/bin/env bash
# MUTANTE da rodada 4: a versao VELHA do gate contra o MESMO estimulo.
#
# Verde na suite nova prova que o novo passa. NAO prova que a classe do defeito
# morreu — para isso e preciso rodar o codigo ANTERIOR contra os mesmos casos e
# ver a suite REPROVAR. Sem este passo, "consertei" e alegacao.
#
# O mutante aqui e cirurgico e reverte exatamente as DUAS linhas do conserto:
#   1. a chamada a `_verify_repo_branches` no gate (o gate volta a medir so o HEAD)
#   2. a inclusao do ANCORA em `_descobrir_worktrees_do_card` (volta o furo G2)
#
# Esperado: os casos G1/B4/G2/recorte-na-janela voltam a FALHAR, e os controles
# positivos continuam passando (um mutante que reprova tudo nao prova nada).
#
# Uso:  bash docs/evidencia/t7e6fb387/mutante-rodada4.sh
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
ALVO="$REPO/hermes_cli/kanban_db.py"
SUITE="tests/hermes_cli/test_kanban_evidence_gate_round4.py"
BACKUP="$(mktemp -t kanban_db_rodada4)"
PY="$REPO/.venv/bin/python"

cd "$REPO" || exit 2
cp "$ALVO" "$BACKUP" || exit 2

restaura() {
  cp "$BACKUP" "$ALVO" && rm -f "$BACKUP"
  echo
  echo "--- RESTAURADO. diff contra o commit (vazio = arvore intacta):"
  git diff --stat -- "$ALVO"
}
trap restaura EXIT

echo "=============================================================================="
echo "BASELINE — o gate CONSERTADO contra a suite da rodada 4"
echo "=============================================================================="
env -u HERMES_KANBAN_DB -u HERMES_KANBAN_TASK -u HERMES_KANBAN_WORKSPACE \
  "$PY" -m pytest "$SUITE" -q -p no:logging --no-header 2>&1 | tail -3
echo

echo "=============================================================================="
echo "MUTANTE 1 — o gate volta a medir SO o HEAD (desliga _verify_repo_branches)"
echo "=============================================================================="
"$PY" - "$ALVO" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
velho = """            medida = _verify_repo_publication(task_id, repo)
            branches = _verify_repo_branches(conn, task_id, repo)
            if branches:
                medida = {**medida, "branches_do_card": branches}
            verified.append(medida)"""
novo = """            verified.append(_verify_repo_publication(task_id, repo))"""
assert velho in s, "ancora do mutante 1 nao encontrada — o conserto mudou de forma"
open(p, "w", encoding="utf-8").write(s.replace(velho, novo))
print("  aplicado: o gate volta a medir so o HEAD")
PYEOF
env -u HERMES_KANBAN_DB -u HERMES_KANBAN_TASK -u HERMES_KANBAN_WORKSPACE \
  "$PY" -m pytest "$SUITE" -q -p no:logging --no-header -rf 2>&1 \
  | grep -E "^(FAILED|[0-9]+ (passed|failed))" || true
cp "$BACKUP" "$ALVO"
echo

echo "=============================================================================="
echo "MUTANTE 2 — o ANCORA sai da descoberta (volta o furo G2 da rodada 3)"
echo "=============================================================================="
"$PY" - "$ALVO" <<'PYEOF'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
velho = """    for i, caminho in enumerate(caminhos):
        if i == 0 or task_id in caminho.name or task_id in str(caminho):"""
novo = """    for i, caminho in enumerate(caminhos):
        if task_id in caminho.name or task_id in str(caminho):"""
assert velho in s, "ancora do mutante 2 nao encontrada — o conserto mudou de forma"
open(p, "w", encoding="utf-8").write(s.replace(velho, novo))
print("  aplicado: o repo ancora deixa de ser medido")
PYEOF
env -u HERMES_KANBAN_DB -u HERMES_KANBAN_TASK -u HERMES_KANBAN_WORKSPACE \
  "$PY" -m pytest "$SUITE" -q -p no:logging --no-header -rf 2>&1 \
  | grep -E "^(FAILED|[0-9]+ (passed|failed))" || true
echo

echo "LEITURA: cada mutante tem de MATAR os casos do furo que ele reintroduz e"
echo "DEIXAR VIVOS os controles positivos. Mutante que reprova tudo nao distingue"
echo "conserto de sensor quebrado."
