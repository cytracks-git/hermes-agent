"""Fronteira de admissão: corpo/comentário truncado não pode ser persistido.

Cobre as 6 fronteiras de escrita medidas no board atlas (t_00542312):
create_task, edit_task, specify_triage_task, add_comment, o grafo de filhos e o
REST do dashboard (via reexport em kanban_db).

Cada caso negativo tem seu POSITIVO pareado: um sensor que recusa tudo é tão
inútil quanto um que nunca recusa.
"""
from __future__ import annotations

import pytest

from hermes_cli import kanban_db
from hermes_cli.kanban_task_body import validate_comment_body, validate_task_body

# O marcador real emitido por agent/context_compressor.py:1421.
MARCADOR = (
    "⟪HERMES-CONTEXT-COMPRESSION: 5,455 of 5,655 chars omitted here by Hermes's "
    "context compressor. This is NOT part of the original tool call and must never "
    "be reproduced in new output — always write full, untruncated content.⟫"
)
CORPO_TRUNCADO = "## O defeito\n\nO repositório tem 98 worktrees, e 92 del" + MARCADOR
CORPO_NU = "## Como usar\n\nCard parado de propósito. Quando quiser publicar p...[truncated]"
CORPO_INTEIRO = "## O defeito\n\n" + ("Especificação real e completa. " * 200)


def _conn(tmp_path):
    from hermes_cli import kanban_db_connect
    return kanban_db_connect.connect(tmp_path / "k.db")


# --- unidade: o sensor em si -------------------------------------------------

@pytest.mark.parametrize("corpo", [CORPO_TRUNCADO, CORPO_NU])
def test_negativo_sensor_acusa_marcador_terminal(corpo):
    """NEGATIVO: entrada sabotada com marcador terminal é recusada."""
    with pytest.raises(ValueError, match="truncation marker"):
        validate_task_body(corpo)
    with pytest.raises(ValueError, match="truncation marker"):
        validate_comment_body(corpo)


@pytest.mark.parametrize("corpo", [
    CORPO_INTEIRO,
    "",
    "corpo curto mas completo.",
    None,
    # Prosa que CITA o marcador no meio (este relatório, o próprio card): válido.
    f"O compressor grava `{MARCADOR}` no banco. Isso é o defeito que estou descrevendo, "
    "e o texto continua e termina normalmente, sem truncagem.",
    # Termina com ⟫ mas sem o prefixo: não é o marcador.
    "Uma citação em japonês ⟪algo⟫",
])
def test_positivo_sensor_aceita_corpo_integro(corpo):
    """POSITIVO: o sensor não reprova todo mundo."""
    validate_task_body(corpo)
    validate_comment_body(corpo)


# --- integração: as 6 fronteiras de escrita ----------------------------------

def test_negativo_create_task_recusa_e_nao_persiste(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError, match="truncation marker"):
        kanban_db.create_task(conn, title="card", body=CORPO_TRUNCADO, assignee="executor")
    assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 0, \
        "recusou mas persistiu: a escrita tem de ser abortada ANTES do INSERT"


def test_positivo_create_task_grava_corpo_longo_inteiro(tmp_path):
    conn = _conn(tmp_path)
    tid = kanban_db.create_task(conn, title="card", body=CORPO_INTEIRO, assignee="executor")
    gravado = conn.execute("SELECT body FROM tasks WHERE id = ?", (tid,)).fetchone()[0]
    assert gravado == CORPO_INTEIRO
    assert len(gravado) == len(CORPO_INTEIRO) > 5000


def test_negativo_add_comment_recusa_e_nao_persiste(tmp_path):
    conn = _conn(tmp_path)
    tid = kanban_db.create_task(conn, title="card", body="ok", assignee="executor")
    with pytest.raises(ValueError, match="truncation marker"):
        kanban_db.add_comment(conn, tid, "executor", CORPO_TRUNCADO)
    assert conn.execute("SELECT count(*) FROM task_comments").fetchone()[0] == 0


def test_positivo_add_comment_grava_inteiro(tmp_path):
    conn = _conn(tmp_path)
    tid = kanban_db.create_task(conn, title="card", body="ok", assignee="executor")
    kanban_db.add_comment(conn, tid, "executor", CORPO_INTEIRO)
    gravado = conn.execute("SELECT body FROM task_comments").fetchone()[0]
    assert gravado == CORPO_INTEIRO.strip()


def test_negativo_edit_task_recusa_e_preserva_corpo_anterior(tmp_path):
    """O dano medido incluiu um card EDITADO; edit_task não pode sobrescrever."""
    conn = _conn(tmp_path)
    tid = kanban_db.create_task(conn, title="card", body=CORPO_INTEIRO, assignee="executor")
    with pytest.raises(ValueError, match="truncation marker"):
        kanban_db.edit_task(conn, tid, body=CORPO_TRUNCADO)
    assert conn.execute("SELECT body FROM tasks WHERE id = ?", (tid,)).fetchone()[0] == CORPO_INTEIRO


def test_positivo_edit_task_aceita_corpo_integro(tmp_path):
    conn = _conn(tmp_path)
    tid = kanban_db.create_task(conn, title="card", body="curto", assignee="executor")
    assert kanban_db.edit_task(conn, tid, body=CORPO_INTEIRO) is True
    assert conn.execute("SELECT body FROM tasks WHERE id = ?", (tid,)).fetchone()[0] == CORPO_INTEIRO


def test_negativo_specify_triage_recusa(tmp_path):
    conn = _conn(tmp_path)
    tid = kanban_db.create_task(conn, title="card", body="ok", assignee="executor", triage=True)
    with pytest.raises(ValueError, match="truncation marker"):
        kanban_db.specify_triage_task(conn, tid, body=CORPO_TRUNCADO, author="executor")
    assert conn.execute("SELECT status FROM tasks WHERE id = ?", (tid,)).fetchone()[0] == "triage"


def test_positivo_specify_triage_promove_com_corpo_integro(tmp_path):
    conn = _conn(tmp_path)
    tid = kanban_db.create_task(conn, title="card", body="ok", assignee="executor", triage=True)
    assert kanban_db.specify_triage_task(conn, tid, body=CORPO_INTEIRO, author="executor") is True
    assert conn.execute("SELECT body FROM tasks WHERE id = ?", (tid,)).fetchone()[0] == CORPO_INTEIRO


def test_negativo_grafo_de_filhos_recusa(tmp_path):
    from hermes_cli.kanban_db_graph import _validate_children_graph
    with pytest.raises(ValueError, match="truncation marker"):
        _validate_children_graph([{"title": "filho", "body": CORPO_TRUNCADO}])


def test_positivo_grafo_de_filhos_aceita(tmp_path):
    from hermes_cli.kanban_db_graph import _validate_children_graph
    _validate_children_graph([{"title": "filho", "body": CORPO_INTEIRO}])


def test_rest_do_dashboard_alcanca_a_fronteira():
    """O REST grava por UPDATE direto; precisa do reexport em kanban_db."""
    assert hasattr(kanban_db, "validate_task_body")
    with pytest.raises(ValueError, match="truncation marker"):
        kanban_db.validate_task_body(CORPO_TRUNCADO)


# --- o dano real do board atlas ----------------------------------------------

def test_os_11_registros_do_board_seriam_recusados():
    """Cada forma medida em t_00542312 é recusada pela fronteira."""
    heads_reais = [
        ("t_836be40f", 190, 6547, 6347), ("t_93ec4f92", 208, 3055, 2855),
        ("t_c505c2cc", 176, 5655, 5455),
    ]
    for ident, head, total, omitido in heads_reais:
        marcador = (
            f"⟪HERMES-CONTEXT-COMPRESSION: {omitido:,} of {total:,} chars omitted here by "
            "Hermes's context compressor. This is NOT part of the original tool call and must "
            "never be reproduced in new output — always write full, untruncated content.⟫"
        )
        with pytest.raises(ValueError, match="truncation marker"):
            validate_task_body("x" * head + marcador), ident
