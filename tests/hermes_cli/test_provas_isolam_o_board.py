"""Sensor: nenhuma prova avulsa pode escrever no board de PRODUCAO.

Existe por um defeito MEDIDO, nao por precaucao. O harness da rodada 2 setava
apenas ``HERMES_HOME`` e criou 10 cards `assignee=worker` no board atlas real;
3 deles ocuparam o teto global de 4 slots do dispatcher enquanto 23 cards de
entrega esperavam em `ready`.

A causa e de PRECEDENCIA, e isso e o que este sensor congela:
``HERMES_KANBAN_DB`` (injetado em todo worker) vence ``HERMES_HOME``. Um script
que sete so o segundo NAO esta isolado, por mais que pareca.

A suite pytest nunca teve o furo — ``tests/conftest.py`` ja limpa esses pins.
O sensor cobre os scripts avulsos de ``docs/evidencia/``, que rodam fora dele.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_EVIDENCIA = Path(__file__).resolve().parents[2] / "docs" / "evidencia" / "t7e6fb387"

# Scripts que constroem cards de kanban e por isso precisam isolar o board.
# Um script que so le (nao chama create_task) nao entra nesta lista.
_ESCREVEM_CARDS = ("extras-gate.py", "prova-board-real.py", "harness-revisor-rodada2.py")


def _fonte(nome: str) -> str:
    caminho = _EVIDENCIA / nome
    if not caminho.exists():
        pytest.skip(f"{nome} nao esta neste worktree")
    return caminho.read_text(encoding="utf-8")


@pytest.mark.parametrize("nome", _ESCREVEM_CARDS)
def test_prova_avulsa_limpa_o_pin_do_board(nome: str):
    """Setar HERMES_HOME nao basta: o pin HERMES_KANBAN_DB tem de ser removido.

    CONTROLE NEGATIVO desta regra: ``test_sensor_acusa_script_que_so_seta_home``
    abaixo constroi um script sem a limpeza e exige que o predicado reprove.
    """
    fonte = _fonte(nome)
    assert _isola_o_board(fonte), (
        f"{nome} cria cards de kanban sem limpar HERMES_KANBAN_DB. Medido: "
        f"o pin do worker vence HERMES_HOME e os fixtures vao para o board de "
        f"producao. Use docs/evidencia/t7e6fb387/isolar_board.py."
    )


def _isola_o_board(fonte: str) -> bool:
    """O script remove o pin de board antes de usar o kanban?

    Aceita as duas formas em uso: o helper ``isolar_board`` ou a limpeza
    explicita do pin.
    """
    if "isolar_board" in fonte:
        return True
    return "HERMES_KANBAN_DB" in fonte and ("pop(" in fonte or "del os.environ" in fonte)


def test_sensor_acusa_script_que_so_seta_home():
    """CONTROLE NEGATIVO: o script vulneravel (a forma exata do defeito original).

    Sem este caso, o teste acima passaria mesmo se o predicado fosse `return
    True` — verde por construcao.
    """
    vulneravel = (
        "import os\n"
        "os.environ['HERMES_HOME'] = '/tmp/qualquer'\n"
        "from hermes_cli import kanban_db as kb\n"
        "kb.create_task(conn, title='t', assignee='worker')\n"
    )
    assert not _isola_o_board(vulneravel), (
        "o predicado do sensor nao acusa nem o defeito original: ele esta "
        "desligado, nao passando"
    )


def test_sensor_aceita_as_duas_formas_de_isolamento():
    """CONTROLE POSITIVO: um sensor que reprova todo mundo e igualmente inutil."""
    via_helper = "from isolar_board import isolar_board\nisolar_board('x-')\n"
    via_pop = "import os\nos.environ.pop('HERMES_KANBAN_DB', None)\n"
    assert _isola_o_board(via_helper)
    assert _isola_o_board(via_pop)


def test_precedencia_medida_do_pin_sobre_o_home(tmp_path: Path):
    """A PREMISSA do sensor, medida de verdade em vez de suposta.

    Roda num subprocesso limpo: se um dia ``HERMES_HOME`` passar a vencer, este
    teste cai e o sensor inteiro deixa de fazer sentido — melhor descobrir aqui
    do que continuar cobrando uma regra obsoleta.
    """
    script = (
        "import os, sys\n"
        f"os.environ['HERMES_KANBAN_DB'] = {str(tmp_path / 'pin' / 'kanban.db')!r}\n"
        f"os.environ['HERMES_HOME'] = {str(tmp_path / 'home')!r}\n"
        "from hermes_cli import kanban_db as kb\n"
        "print(kb.kanban_db_path())\n"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_")}
    env["PATH"] = os.environ.get("PATH", "")
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True,
        timeout=120, cwd=str(Path(__file__).resolve().parents[2]), env=env,
    )
    assert proc.returncode == 0, proc.stderr
    destino = proc.stdout.strip().splitlines()[-1]
    assert destino == str(tmp_path / "pin" / "kanban.db"), (
        f"a premissa do sensor mudou: com o pin setado, kanban_db_path() deu "
        f"{destino!r}. Revisar isolar_board.py antes de confiar nele."
    )
