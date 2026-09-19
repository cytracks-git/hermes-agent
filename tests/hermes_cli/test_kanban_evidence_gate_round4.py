"""Rodada 4 do gate de evidencia: o gate media SO o HEAD, e `git checkout` o desligava.

O revisor mediu (comentario de REVISAO RODADA 3, lente CONTRATO) e eu reproduzi
com o harness DELE (`/tmp/rev3_t7e/g_so_head.py`) antes de escrever uma linha:

    G3 CONTROLE 1 branch nao publicada, HEAD nela  -> RECUSOU  (ok)
    G1 duas branches; HEAD na PUBLICADA            -> ACEITOU status=done => FURO
    G2 worktree do card publicado, repo PRINCIPAL com branch orfa
                                                    -> ACEITOU status=done => FURO

G1 nao precisa de ma-fe: e o fluxo normal deste board (separar conserto e
evidencia em duas ramas, empurrar uma, fechar). E a classe de origem do card —
"5 commits que so existiam no disco".

RECORTE DECLARADO, e ele foi MEDIDO, nao suposto
------------------------------------------------
Medir TODAS as `refs/heads` alcanca **638 branches nao publicadas em 93 repos**
deste host (`docs/evidencia/t7e6fb387/pop-branches-rodada4.py`), quase todas de
cards e meses alheios, compartilhadas pelos 87 worktrees do clm360. Cobrar
todas elas travaria o board — a paranoia que o card proibe por escrito.

O recorte implementado: **as branches que o HEAD DESTE worktree apontou dentro
da janela do card**. A fonte e o reflog do HEAD, que e POR WORKTREE (arquivo
proprio em `.git/worktrees/<nome>/logs/HEAD`) e quem escreve e o git, a cada
checkout/commit — inclusive o `git checkout main` do bypass. A janela vem de
`task_runs.started_at`, que o board escreve, nao o worker.

Medido com esse recorte (`pop-reflog-rodada4.py`): **5 branches em 5 worktrees**,
e as 5 sao trabalho de card real nao publicado. 638 -> 5.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc


def _git(*args: str, check: bool = True) -> str:
    r = subprocess.run(["git", *args], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=60)
    if check:
        assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout


@pytest.fixture
def kanban_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / ".hermes"
    home.mkdir()
    ws_root = home / "kanban" / "workspaces"
    ws_root.mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("HERMES_KANBAN_WORKSPACES_ROOT", str(ws_root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


def _base(d: Path, nome: str = "project") -> tuple[Path, Path]:
    """Clone com origin bare local e um commit ja publicado em `main`."""
    origin = d / f"{nome}-origin.git"
    _git("init", "--bare", "-b", "main", str(origin))
    proj = d / nome
    _git("clone", str(origin), str(proj))
    _git("-C", str(proj), "config", "user.email", "t@example.com")
    _git("-C", str(proj), "config", "user.name", "t")
    (proj / "README.md").write_text("base\n", encoding="utf-8")
    _git("-C", str(proj), "add", "README.md")
    _git("-C", str(proj), "commit", "-m", "init")
    _git("-C", str(proj), "push", "origin", "HEAD:main")
    return proj, origin


def _commit_em_branch(repo: Path, branch: str, arq: str) -> str:
    _git("-C", str(repo), "checkout", "-b", branch)
    (repo / arq).write_text(f"# {arq}\n", encoding="utf-8")
    _git("-C", str(repo), "add", arq)
    _git("-C", str(repo), "commit", "-m", f"trabalho em {branch}")
    return _git("-C", str(repo), "rev-parse", "HEAD").strip()


def _claimed_task(conn, ws: Path, kind: str = "dir") -> str:
    tid = kb.create_task(conn, title="t", assignee="worker")
    with kb.write_txn(conn):
        conn.execute(
            "UPDATE tasks SET workspace_kind=?, workspace_path=?, status='ready' WHERE id=?",
            (kind, str(ws), tid))
    assert kb.claim_task(conn, tid, claimer="worker") is not None
    return tid


def _recuou_no_tempo(conn, tid: str, segundos: int) -> None:
    """Empurra `started_at` do run para tras: simula card mais antigo.

    Usado para provar que a JANELA recorta de verdade — sem isso o teste da
    janela passaria por construcao, ja que tudo acontece no mesmo segundo.
    """
    with kb.write_txn(conn):
        conn.execute("UPDATE task_runs SET started_at = ? WHERE task_id = ?",
                     (int(time.time()) - segundos, tid))


def _events(conn, tid: str) -> list[str]:
    return [r["kind"] for r in conn.execute(
        "SELECT kind FROM task_events WHERE task_id=? ORDER BY id", (tid,))]


# ---------------------------------------------------------------------------
# G1 — duas branches de trabalho, HEAD na publicada. O FURO BLOQUEANTE.
# ---------------------------------------------------------------------------


def test_g1_branch_orfa_fora_do_head_recusa(kanban_home, tmp_path):
    """Worker trabalha em `conserto`, muda para `evidencia`, empurra SO essa.

    O commit de `conserto` fica so no disco e o card fechava `done`. Tem de
    RECUSAR, nomeando a branch que ficou para tras.

    O card e criado ANTES do trabalho, que e a ordem real do board: o
    dispatcher reivindica, o worker so entao commita.
    """
    with kbc.connect() as conn:
        proj, _ = _base(tmp_path / "g1")
        tid = _claimed_task(conn, proj)

        sha_orfa = _commit_em_branch(proj, "conserto", "conserto.py")
        _git("-C", str(proj), "checkout", "main")
        _commit_em_branch(proj, "evidencia", "evid.md")
        _git("-C", str(proj), "push", "-u", "origin", "evidencia")

        with pytest.raises(kb.UnpushedWorkError) as exc:
            kb.complete_task(conn, tid, summary="Implementei, testei, tudo passou.")

        assert exc.value.branch == "conserto", (
            f"a recusa tem de NOMEAR a branch orfa, recebi {exc.value.branch!r}")
        assert exc.value.head_sha == sha_orfa
        assert kb.get_task(conn, tid).status == "running"
        assert "completion_blocked_unpushed" in _events(conn, tid)


def test_g1_controle_positivo_as_duas_branches_publicadas_fecha(kanban_home, tmp_path):
    """MESMO cenario, unica variavel: `conserto` tambem foi empurrada. FECHA.

    Sem este controle o caso acima so provaria que o gate aprendeu a recusar.
    """
    with kbc.connect() as conn:
        proj, _ = _base(tmp_path / "g1b")
        tid = _claimed_task(conn, proj)

        _commit_em_branch(proj, "conserto", "conserto.py")
        _git("-C", str(proj), "push", "-u", "origin", "conserto")
        _git("-C", str(proj), "checkout", "main")
        _commit_em_branch(proj, "evidencia", "evid.md")
        _git("-C", str(proj), "push", "-u", "origin", "evidencia")

        assert kb.complete_task(conn, tid, summary="empurrei as duas") is True
        assert kb.get_task(conn, tid).status == "done"


# ---------------------------------------------------------------------------
# B4 — o contorno de UMA LINHA: `git checkout main` desligava o gate
# ---------------------------------------------------------------------------


def test_b4_checkout_para_branch_publicada_nao_desliga_o_gate(kanban_home, tmp_path):
    """Worker commita em `trabalho`, roda `git checkout main`, fecha o card.

    Antes: ACEITOU, e o commit ficou orfao. O reflog do HEAD registra o
    checkout, e o git que escreve essa linha, nao o worker.
    """
    with kbc.connect() as conn:
        proj, origin = _base(tmp_path / "b4")
        tid = _claimed_task(conn, proj)

        sha = _commit_em_branch(proj, "trabalho-do-card", "entrega.py")
        _git("-C", str(proj), "checkout", "main")

        with pytest.raises(kb.UnpushedWorkError) as exc:
            kb.complete_task(conn, tid, summary="pronto")

        assert exc.value.branch == "trabalho-do-card"
        assert exc.value.head_sha == sha
        # Conferencia por fora: a branch continua ausente do remoto.
        assert _git("-C", str(proj), "ls-remote", str(origin),
                    "refs/heads/trabalho-do-card").strip() == ""


def test_b4_controle_positivo_checkout_depois_do_push_fecha(kanban_home, tmp_path):
    """MESMO checkout, unica variavel: o `git push` antes. Tem de FECHAR."""
    with kbc.connect() as conn:
        proj, _ = _base(tmp_path / "b4b")
        tid = _claimed_task(conn, proj)

        _commit_em_branch(proj, "trabalho-do-card", "entrega.py")
        _git("-C", str(proj), "push", "-u", "origin", "trabalho-do-card")
        _git("-C", str(proj), "checkout", "main")

        assert kb.complete_task(conn, tid, summary="empurrei antes de trocar") is True
        assert kb.get_task(conn, tid).status == "done"


# ---------------------------------------------------------------------------
# RECORTE — o gate nao pode virar paranoia. Cada limite tem teste proprio.
# ---------------------------------------------------------------------------


def test_recorte_branch_que_o_card_nunca_tocou_nao_trava(kanban_home, tmp_path):
    """Branch suja preexistente, que o HEAD deste card NUNCA apontou. FECHA.

    E o caso dos 638: 87 worktrees do clm360 compartilham branches de meses
    alheios. Cobrar todas elas congelaria o board.
    """
    with kbc.connect() as conn:
        proj, _ = _base(tmp_path / "rec1")
        # Trabalho de OUTRA pessoa, anterior ao card, sem passar pelo HEAD daqui.
        _commit_em_branch(proj, "trabalho-de-terceiro", "alheio.py")
        _git("-C", str(proj), "checkout", "main")

        # O card comeca AGORA; o reflog acima fica para tras da janela.
        tid = _claimed_task(conn, proj)
        marco = int(time.time())
        while int(time.time()) <= marco:
            time.sleep(0.2)  # garante epoch estritamente maior que o checkout
        with kb.write_txn(conn):
            conn.execute("UPDATE task_runs SET started_at = ? WHERE task_id = ?",
                         (int(time.time()), tid))

        assert kb.complete_task(conn, tid, summary="so li, nao commitei") is True
        assert kb.get_task(conn, tid).status == "done"


def test_recorte_controle_positivo_a_mesma_branch_dentro_da_janela_recusa(
        kanban_home, tmp_path):
    """MESMA branch suja, unica variavel: o card a tocou DENTRO da janela.

    Este e o controle que prova que a janela recorta por TEMPO, e nao que o
    gate simplesmente nao enxerga aquela branch.
    """
    with kbc.connect() as conn:
        proj, _ = _base(tmp_path / "rec2")
        _commit_em_branch(proj, "trabalho-de-terceiro", "alheio.py")
        _git("-C", str(proj), "checkout", "main")

        tid = _claimed_task(conn, proj)
        _recuou_no_tempo(conn, tid, 3600)  # card comecou 1h atras: engloba o checkout

        with pytest.raises(kb.UnpushedWorkError) as exc:
            kb.complete_task(conn, tid, summary="pronto")
        assert exc.value.branch == "trabalho-de-terceiro"


def test_recorte_leitura_pura_continua_fechando(kanban_home, tmp_path):
    """Card de leitura: workspace nao-git, nenhum commit. Tem de FECHAR."""
    with kbc.connect() as conn:
        ws = kanban_home / "kanban" / "workspaces" / "ws-leitura-r4"
        ws.mkdir(parents=True)
        (ws / "notas.md").write_text("levantei\n", encoding="utf-8")
        tid = _claimed_task(conn, ws, kind="scratch")
        assert kb.complete_task(conn, tid, summary="li e medi") is True
        assert kb.get_task(conn, tid).status == "done"


def test_recorte_branch_apagada_depois_nao_trava(kanban_home, tmp_path):
    """O card tocou uma branch e depois a APAGOU (trabalho descartado). FECHA.

    O reflog guarda o nome, mas a ref nao existe mais: nao ha commit a cobrar,
    e recusar aqui seria cobrar por um fantasma.
    """
    with kbc.connect() as conn:
        proj, _ = _base(tmp_path / "rec3")
        _commit_em_branch(proj, "tentativa-descartada", "rascunho.py")
        _git("-C", str(proj), "checkout", "main")
        _git("-C", str(proj), "branch", "-D", "tentativa-descartada")

        tid = _claimed_task(conn, proj)
        _recuou_no_tempo(conn, tid, 3600)
        assert kb.complete_task(conn, tid, summary="descartei a tentativa") is True
        assert kb.get_task(conn, tid).status == "done"


# ---------------------------------------------------------------------------
# G2 — worktree do card publicado, repo ANCORA com branch orfa
# ---------------------------------------------------------------------------


def test_g2_repo_ancora_com_branch_orfa_e_medido(kanban_home, tmp_path):
    """O card trabalha num worktree publicado; o repo principal ficou sujo.

    O worktree do card e alcancavel pelo board, e o repo ancora e alcancavel
    pelo worktree. O trabalho do ancora tocado na janela do card tem de contar.
    """
    with kbc.connect() as conn:
        d = tmp_path / "g2"
        d.mkdir()
        proj, _ = _base(d)
        sha_orfa = _commit_em_branch(proj, "trabalho-principal", "main-work.py")
        _git("-C", str(proj), "checkout", "main")

        wt = d / "wt-card"
        _git("-C", str(proj), "worktree", "add", "-b", "card/x", str(wt))
        (wt / "b.py").write_text("y\n", encoding="utf-8")
        _git("-C", str(wt), "add", "b.py")
        _git("-C", str(wt), "commit", "-m", "card")
        _git("-C", str(wt), "push", "-u", "origin", "card/x")

        tid = _claimed_task(conn, wt)
        _recuou_no_tempo(conn, tid, 3600)

        with pytest.raises(kb.UnpushedWorkError) as exc:
            kb.complete_task(conn, tid, summary="meu worktree esta publicado")
        assert exc.value.head_sha == sha_orfa
        assert kb.get_task(conn, tid).status == "running"


def test_g2_controle_positivo_ancora_limpo_fecha(kanban_home, tmp_path):
    """MESMA topologia, unica variavel: o ancora nao tem branch suja. FECHA."""
    with kbc.connect() as conn:
        d = tmp_path / "g2b"
        d.mkdir()
        proj, _ = _base(d)
        wt = d / "wt-card"
        _git("-C", str(proj), "worktree", "add", "-b", "card/x", str(wt))
        (wt / "b.py").write_text("y\n", encoding="utf-8")
        _git("-C", str(wt), "add", "b.py")
        _git("-C", str(wt), "commit", "-m", "card")
        _git("-C", str(wt), "push", "-u", "origin", "card/x")

        tid = _claimed_task(conn, wt)
        _recuou_no_tempo(conn, tid, 3600)
        assert kb.complete_task(conn, tid, summary="tudo publicado") is True
        assert kb.get_task(conn, tid).status == "done"


# ---------------------------------------------------------------------------
# FAIL-CLOSED — nao conseguir LER o reflog nao e o mesmo que estar limpo
# ---------------------------------------------------------------------------


def test_reflog_ilegivel_vira_nao_medido_e_nao_verde(kanban_home, tmp_path, monkeypatch):
    """Se a sonda do reflog nao roda, o gate tem de RECUSAR, nao aprovar.

    O contrario e o falso-verde que este gate inteiro existe para matar.
    """
    with kbc.connect() as conn:
        proj, _ = _base(tmp_path / "fc")
        _commit_em_branch(proj, "trabalho", "x.py")
        _git("-C", str(proj), "push", "-u", "origin", "trabalho")

        original = kb._probe_git

        def sonda_quebrada(repo, *args, **kw):
            if args and args[0] == "reflog":
                return (subprocess.CompletedProcess(args=["git", *args], returncode=-1,
                                                    stdout="", stderr=""),
                        f"`git reflog` could not run in {repo}: simulado")
            return original(repo, *args, **kw)

        monkeypatch.setattr(kb, "_probe_git", sonda_quebrada)

        tid = _claimed_task(conn, proj)
        with pytest.raises(kb.UnmeasuredEvidenceError) as exc:
            kb.complete_task(conn, tid, summary="pronto")
        assert exc.value.reason == "reflog_probe_failed"
        assert kb.get_task(conn, tid).status == "running"


def test_fail_closed_controle_positivo_sonda_sa_fecha(kanban_home, tmp_path):
    """MESMO cenario com a sonda intacta: tem de FECHAR.

    Sem este controle, o teste acima nao distingue "fail-closed funciona" de
    "este cenario nunca fecharia".
    """
    with kbc.connect() as conn:
        proj, _ = _base(tmp_path / "fcb")
        _commit_em_branch(proj, "trabalho", "x.py")
        _git("-C", str(proj), "push", "-u", "origin", "trabalho")

        tid = _claimed_task(conn, proj)
        assert kb.complete_task(conn, tid, summary="pronto") is True
        assert kb.get_task(conn, tid).status == "done"
