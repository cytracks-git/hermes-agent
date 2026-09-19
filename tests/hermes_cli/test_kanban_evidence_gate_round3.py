"""Round 3 do gate de evidencia: as TRES falhas medidas pelo revisor na rodada 2.

O parecer da rodada 2 (comentario 414 do card t_7e6fb387) foi tratado como
alegacao ate eu reproduzir o harness dele. Reproduziu: 5/8 conformes, com

  W1  scratch + trabalho num repo NAO declarado -> ACEITOU (devia RECUSAR)
  W3  worker troca o `origin` por um bare repo que ele mesmo criou -> ACEITOU
  W4  HEAD publicado + arquivos NAO commitados -> ACEITOU e o cleanup APAGOU

Este modulo e o RED dessa reprova. Cada caso vem com CONTROLE POSITIVO no mesmo
arquivo: um gate que recusa todo mundo e tao inutil quanto um que nunca recusa.

RECORTE DECLARADO (medido, nao suposto): a descoberta so alcanca repositorios
ligados ao card por uma fonte que o worker nao escreve — o workspace do card, os
repos aninhados nele, e os worktrees do repo ancora cujo path/branch casa o task
id. Um worktree criado num repo que o board nunca viu continua invisivel; isso
esta declarado em docs/evidencia/t7e6fb387/RODADA-3-MEDIDO.md com o custo de
cobrir, em vez de virar caminho silencioso.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_connect as kbc
from hermes_cli import kanban_db_workspace as kbw


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
    # O rmtree de _cleanup_workspace so roda DENTRO de um root gerenciado: sem
    # isto, o caso W4 "passaria" pelo guarda de contencao, nao pelo conserto.
    monkeypatch.setenv("HERMES_KANBAN_WORKSPACES_ROOT", str(ws_root))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    kb._INITIALIZED_PATHS.clear()
    kb.init_db()
    return home


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Clone com origin de verdade (bare local), um commit publicado."""
    origin = tmp_path / "origin.git"
    _git("init", "--bare", str(origin))
    project = tmp_path / "project"
    _git("clone", str(origin), str(project))
    _git("-C", str(project), "config", "user.email", "t@example.com")
    _git("-C", str(project), "config", "user.name", "t")
    (project / "README.md").write_text("hello\n", encoding="utf-8")
    _git("-C", str(project), "add", "README.md")
    _git("-C", str(project), "commit", "-m", "init")
    _git("-C", str(project), "push", "origin", "HEAD")
    return project


def _managed_scratch(kanban_home: Path, name: str) -> Path:
    ws = kanban_home / "kanban" / "workspaces" / name
    ws.mkdir(parents=True)
    return ws


def _claimed_task(conn, **cols) -> str:
    tid = kb.create_task(conn, title="t", assignee="worker")
    if cols:
        sets = ", ".join(f"{k}=?" for k in cols)
        with kb.write_txn(conn):
            conn.execute(f"UPDATE tasks SET {sets} WHERE id=?", (*cols.values(), tid))
    with kb.write_txn(conn):
        conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
    assert kb.claim_task(conn, tid, claimer="worker") is not None
    return tid


def _commit(wt: Path, name: str = "f.txt", body: str = "x") -> str:
    (wt / name).write_text(body, encoding="utf-8")
    _git("-C", str(wt), "add", name)
    _git("-C", str(wt), "commit", "-m", f"trabalho em {name}")
    return _git("-C", str(wt), "rev-parse", "HEAD").strip()


def _events(conn, tid: str) -> list[str]:
    return [r["kind"] for r in conn.execute(
        "SELECT kind FROM task_events WHERE task_id=? ORDER BY id", (tid,))]


def _event_payload(conn, tid: str, event_type: str) -> dict:
    row = conn.execute(
        "SELECT payload FROM task_events WHERE task_id=? AND kind=? "
        "ORDER BY id DESC LIMIT 1", (tid, event_type)).fetchone()
    assert row is not None, f"evento {event_type} nao gravado para {tid}"
    return json.loads(row["payload"])


# ---------------------------------------------------------------------------
# FALHA 1 — omitir metadata nao pode ser o atalho
#
# A rodada 2 so media `workspace_path` + caminhos DECLARADOS em metadata. Medido
# no board de producao: 177 de 193 runs com metadata CALAM sobre o repo, e ha 5
# cards reais cujo trabalho vive num repo git ANINHADO no proprio workspace
# (`<workspace>/repo`, `<workspace>/review`). Nenhum deles era medido.
# ---------------------------------------------------------------------------


def test_f1_repo_aninhado_no_workspace_sem_metadata_e_medido(kanban_home, tmp_path):
    """Repo git dentro do workspace scratch, commit NAO empurrado, metadata VAZIA.

    E a forma real do board (`<workspace>/repo`). O worker nao declara nada.
    Tem de RECUSAR: a descoberta nao pode depender do que o alegante escreve.
    """
    with kbc.connect() as conn:
        ws = _managed_scratch(kanban_home, "ws-f1")
        tid = _claimed_task(conn, workspace_kind="scratch", workspace_path=str(ws))

        origin = tmp_path / "o-f1.git"
        _git("init", "--bare", str(origin))
        nested = ws / "repo"
        _git("clone", str(origin), str(nested))
        _git("-C", str(nested), "config", "user.email", "t@example.com")
        _git("-C", str(nested), "config", "user.name", "t")
        _commit(nested)

        with pytest.raises(kb.UnpushedWorkError) as exc:
            kb.complete_task(conn, tid, summary="Implementei, testei, tudo passou.")

        assert str(nested) in str(exc.value.repo_path)
        assert kb.get_task(conn, tid).status == "running"
        assert "completion_blocked_unpushed" in _events(conn, tid)


def test_f1_controle_positivo_repo_aninhado_publicado_fecha(kanban_home, tmp_path):
    """MESMO cenario, unica variavel: o `git push`. Tem de FECHAR.

    Sem este controle, o caso acima so provaria que o gate aprendeu a recusar.
    """
    with kbc.connect() as conn:
        ws = _managed_scratch(kanban_home, "ws-f1b")
        tid = _claimed_task(conn, workspace_kind="scratch", workspace_path=str(ws))

        origin = tmp_path / "o-f1b.git"
        _git("init", "--bare", str(origin))
        nested = ws / "repo"
        _git("clone", str(origin), str(nested))
        _git("-C", str(nested), "config", "user.email", "t@example.com")
        _git("-C", str(nested), "config", "user.name", "t")
        _commit(nested)
        _git("-C", str(nested), "push", "origin", "HEAD")

        assert kb.complete_task(conn, tid, summary="empurrei") is True
        assert kb.get_task(conn, tid).status == "done"


def test_f1_worktree_do_card_por_task_id_sem_metadata_e_medido(kanban_home, repo):
    """Worker cria worktree no repo ancora e CALA.

    A ancora e alcancavel pelo card (o workspace aponta para o repo); o worktree
    carrega o task id no path. Fonte objetiva, nao declarada pelo worker.
    """
    with kbc.connect() as conn:
        tid = _claimed_task(conn, workspace_kind="dir", workspace_path=str(repo))
        externo = repo / ".worktrees" / f"wt-{tid}"
        kbw._ensure_git_worktree(repo, externo, f"wt/{tid}")
        _commit(externo)

        with pytest.raises(kb.UnpushedWorkError):
            kb.complete_task(conn, tid, summary="pronto")
        assert kb.get_task(conn, tid).status == "running"


def test_f1_controle_positivo_worktree_alheio_nao_trava_o_card(kanban_home, repo):
    """Worktree de OUTRO card, sujo e nao empurrado, no mesmo repo ancora.

    Nao pode travar ESTE card: senao um worktree esquecido de terceiros congela
    o board inteiro — a paranoia que o recorte do card proibe.
    """
    with kbc.connect() as conn:
        tid = _claimed_task(conn, workspace_kind="dir", workspace_path=str(repo))
        alheio = repo / ".worktrees" / "wt-t_00000000"
        kbw._ensure_git_worktree(repo, alheio, "wt/t_00000000")
        _commit(alheio)
        _git("-C", str(repo), "push", "origin", "HEAD")

        assert kb.complete_task(conn, tid, summary="meu escopo esta publicado") is True
        assert kb.get_task(conn, tid).status == "done"


def test_f1_leitura_pura_continua_fechando(kanban_home):
    """Controle do recorte: scratch nao-git, so notas. Tem de FECHAR."""
    with kbc.connect() as conn:
        ws = _managed_scratch(kanban_home, "ws-leitura")
        (ws / "notas.md").write_text("levantei\n", encoding="utf-8")
        tid = _claimed_task(conn, workspace_kind="scratch", workspace_path=str(ws))
        assert kb.complete_task(conn, tid, summary="li e medi") is True
        assert kb.get_task(conn, tid).status == "done"


# ---------------------------------------------------------------------------
# FALHA 2 — o worker nao controla a resposta do remoto, mas controla QUAL remoto
#
# Proibir remoto local quebraria os proprios testes (bare local legitimo). O que
# se corrige aqui e a INVISIBILIDADE: a URL que aprovou o fechamento passa a
# ficar gravada, entao a troca de `origin` fica auditavel em vez de silenciosa.
# ---------------------------------------------------------------------------


def test_f2_url_do_remoto_que_aprovou_fica_gravada(kanban_home, repo, tmp_path):
    """Worker aponta `origin` para um bare repo que ele criou e empurra.

    O gate fecha (limitacao declarada), mas o evento tem de registrar a URL que
    aprovou — sem isso a forja e invisivel para quem audita depois.
    """
    with kbc.connect() as conn:
        tid = _claimed_task(conn, workspace_kind="dir", workspace_path=str(repo))
        _commit(repo)
        fake = tmp_path / "remoto-de-mentira.git"
        _git("init", "--bare", str(fake))
        _git("-C", str(repo), "remote", "set-url", "origin", str(fake))
        _git("-C", str(repo), "push", "origin", "HEAD")

        assert kb.complete_task(conn, tid, summary="empurrei") is True

        payload = _event_payload(conn, tid, "completion_evidence_verified")
        urls = [r.get("remote_url") for r in payload["repos"]]
        assert str(fake) in urls, (
            f"a URL do remoto que aprovou tem de ficar gravada; payload={payload}")


# ---------------------------------------------------------------------------
# FALHA 3 — metade da motivacao do card: "53 arquivos em /tmp"
#
# `_cleanup_worktree_workspace` preserva arvore suja; o caminho `scratch` fazia
# `shutil.rmtree` sem consultar nada. Medido no board: 27 workspaces scratch com
# arquivos, o maior com 737 MB.
# ---------------------------------------------------------------------------


def test_f3_trabalho_nao_commitado_sobrevive_ao_fechamento(kanban_home):
    """Card fecha, mas o trabalho que sumiria NAO e apagado."""
    with kbc.connect() as conn:
        ws = _managed_scratch(kanban_home, "ws-f3")
        entregavel = ws / "trabalho-de-8-horas.py"
        entregavel.write_text("# 8 horas, nunca commitado\n", encoding="utf-8")

        tid = _claimed_task(conn, workspace_kind="scratch", workspace_path=str(ws))
        assert kb.complete_task(conn, tid, summary="Entreguei. 53 arquivos novos.") is True

    assert entregavel.exists(), (
        "o cleanup apagou trabalho nao commitado: e a segunda perda que o card "
        "nasce para impedir")
    with kbc.connect() as conn:
        assert "workspace_preserved_unpublished" in _events(conn, tid)


def test_f3_controle_positivo_workspace_vazio_e_removido(kanban_home):
    """Sem isto, 'preservar' viraria vazamento de disco: o vazio tem de sumir.

    Medido no board: 22 dos 69 workspaces scratch estao vazios.
    """
    with kbc.connect() as conn:
        ws = _managed_scratch(kanban_home, "ws-f3-vazio")
        tid = _claimed_task(conn, workspace_kind="scratch", workspace_path=str(ws))
        assert kb.complete_task(conn, tid, summary="nada a preservar") is True
    assert not ws.exists(), "workspace vazio continua sendo removido"


def test_f3_controle_positivo_conteudo_ja_duravel_e_removido(kanban_home):
    """Arquivo ja copiado para os attachments do card NAO justifica preservar.

    Este e o contrato que `test_complete_task_persists_scratch_artifacts_before_cleanup`
    ja cobra: entregue por canal duravel, o scratch pode ir embora.
    """
    with kbc.connect() as conn:
        ws = _managed_scratch(kanban_home, "ws-f3-duravel")
        art = ws / "relatorio.md"
        art.write_text("# medicoes\n", encoding="utf-8")
        tid = _claimed_task(conn, workspace_kind="scratch", workspace_path=str(ws))
        assert kb.complete_task(
            conn, tid, summary="anexei", metadata={"artifacts": [str(art)]}) is True
        assert [a.filename for a in kb.list_attachments(conn, tid)] == ["relatorio.md"]
    assert not ws.exists(), (
        "conteudo ja duravel nos attachments nao pode segurar o workspace")


def test_f3_preservar_nao_bloqueia_o_fechamento(kanban_home):
    """Preservar e efeito colateral do cleanup, nunca veto.

    Um board que nao fecha card e pior que um que fecha demais (restricao do
    card). Preservacao NAO pode virar uma quarta classe de recusa.
    """
    with kbc.connect() as conn:
        ws = _managed_scratch(kanban_home, "ws-f3-naoveta")
        (ws / "rascunho.txt").write_text("qualquer coisa\n", encoding="utf-8")
        tid = _claimed_task(conn, workspace_kind="scratch", workspace_path=str(ws))
        assert kb.complete_task(conn, tid, summary="fecha mesmo assim") is True
        assert kb.get_task(conn, tid).status == "done"
