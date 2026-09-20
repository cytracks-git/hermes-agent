"""Fixtures do contrato de aprovação humana persistente (t_069cfdac / t_78aaa333).

Prova as PRECONDIÇÕES verificáveis do contrato **v2**
(``docs/evidencia/t_78aaa333/contrato-aprovacao-humana-v2.md``) contra o código nativo
real, em banco temporário. Verde = a precondição vale hoje; RED esperado = a peça ainda
não existe e o contrato diz que ela precisa existir.

O que estas fixtures NÃO provam (registrado na §8 do contrato): entrega real de aviso,
comportamento da UI instalada, e isolamento contra processo hostil de mesmo UID.

Roda pelo runner do repositório (``scripts/run_tests.sh``), nunca ``pytest`` puro.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import textwrap

import pytest

from hermes_cli import kanban_db


# --------------------------------------------------------------------------
# Banco temporário real (sem schema/banco vivo — freeze desta etapa)
# --------------------------------------------------------------------------

@pytest.fixture()
def conn(tmp_path):
    # kanban_db.connect é ponteiro de compat (proibido in-tree); usa o módulo que define.
    from hermes_cli import kanban_db_connect

    db = kanban_db.init_db(db_path=tmp_path / "kanban.db")
    c = kanban_db_connect.connect(db)
    yield c
    c.close()


def _task(conn: sqlite3.Connection, **kw) -> str:
    return kanban_db.create_task(
        conn, title=kw.pop("title", "t"), assignee=kw.pop("assignee", "executor"), **kw)


# ==========================================================================
# §1 — fronteira de autoria: nenhuma porta genérica decide
# ==========================================================================

def test_c23_comentario_no_card_nao_e_aceite_tecnico(conn):
    """C-23: add_comment grava texto e nada mais — não muda status nem decide."""
    tid = _task(conn)
    before = kanban_db.get_task(conn, tid).status
    kanban_db.add_comment(conn, tid, "h1", "aprovado, pode escrever")
    after = kanban_db.get_task(conn, tid)
    assert after.status == before
    # E o comentário não criou nenhum registro de decisão.
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "approval_requests" not in tables or not conn.execute(
        "SELECT COUNT(*) FROM approval_requests").fetchone()[0]


def test_c24_patch_generico_do_dashboard_nao_tem_verbo_de_aprovacao(conn):
    """C-24: o dispatch de status do dashboard não expõe verbo de decisão humana.

    Contrato §1.2 A-3: a aprovação nunca entra como status genérico editável por
    ``PATCH /tasks/{id}`` ou ``POST /tasks/bulk``.

    Em v1 isto ficou PULADO por falta de ``fastapi`` no lab. Em v2 o lab passou a montar
    fastapi/starlette/multipart no ``site-packages`` do container (``PYTHONPATH`` NÃO
    serve: ``run_tests.sh`` roda sob ``env -i`` e derruba a variável), e o import é real;
    o ``importorskip`` fica só como rede de segurança para quem rodar fora do lab.
    """
    plugin_api = pytest.importorskip(
        "plugins.kanban.dashboard.plugin_api",
        reason="dashboard exige fastapi; a precondição é do backend do dashboard")

    verbos = set(plugin_api._STATUS_HANDLERS)
    assert verbos, "dispatch vazio — a fixture não mediu nada"
    proibidos = {"approve", "approved", "waiting_approval", "approval", "grant"}
    assert not (verbos & proibidos), f"verbo de decisão exposto no PATCH genérico: {verbos & proibidos}"


def test_c25_nenhuma_ferramenta_kanban_do_worker_aprova():
    """C-25: o toolset que o worker enxerga não carrega verbo de decisão humana."""
    import tools.kanban_tools  # noqa: F401  (registra ao importar)
    from tools.registry import registry

    nomes = set(registry.get_tool_names_for_toolset("kanban"))
    assert nomes, "toolset kanban vazio — a fixture não mediu nada"
    aprovadores = {n for n in nomes if "approv" in n or "grant" in n}
    assert not aprovadores, f"ferramenta de worker que decide aprovação: {aprovadores}"


# ==========================================================================
# §1/§4 — a guarda protegida preserva suas propriedades
# ==========================================================================

def test_c26_portao_protegido_ignora_yolo_enquanto_o_gate_comum_o_honra(tmp_path, monkeypatch):
    """C-26: com --yolo ligado, o portão protegido AINDA exige humano.

    Controle positivo na mesma medição: o gate comum (``~/.ssh/config``), que por
    contrato honra yolo, libera no mesmo estado. Se os dois se comportarem igual, a
    fixture acusa — é isso que separa "portão próprio" de "mais um gate".
    """
    import tools.approval as approval
    from tools import approval_context
    from tools import file_tools_write_guards as g

    chave = "fixture-yolo"
    token = approval_context.set_current_session_key(chave)
    try:
        monkeypatch.setattr(approval, "_gateway_notify_cbs", {}, raising=False)
        monkeypatch.setattr(
            "tools.terminal_tool._get_approval_callback", lambda: None, raising=False)
        approval.enable_session_yolo(chave)
        assert approval.is_session_yolo_enabled(chave) is True  # a precondição vale

        protegido = g._request_protected_instruction_approval(["AGENTS.md"], task_id="fixture")
        assert protegido is not None, "yolo liberou escrita em arquivo protegido"
        assert "BLOCKED" in protegido

        # Controle positivo: o gate que honra yolo libera no MESMO estado.
        ssh = tmp_path / ".ssh" / "config"
        ssh.parent.mkdir(parents=True)
        ssh.write_text("Host x\n")
        monkeypatch.setattr(
            "agent.file_safety.is_write_approval_required", lambda p: True, raising=False)
        comum = g._check_approval_required_write([str(ssh)], task_id="fixture")
        assert comum is None, (
            "o gate comum também bloqueou sob yolo — a medição não distingue os dois portões")
    finally:
        approval.disable_session_yolo(chave)
        approval.clear_session(chave)
        approval_context.reset_current_session_key(token)


def test_c27_sem_canal_humano_falha_fechado(monkeypatch):
    """C-27 (RED original de t_78aaa333): sem callback e sem gateway, nega — não aprova."""
    from tools import file_tools_write_guards as g

    import tools.approval as approval
    monkeypatch.setattr(approval, "_gateway_notify_cbs", {}, raising=False)
    monkeypatch.setattr(
        "tools.terminal_tool._get_approval_callback", lambda: None, raising=False)

    err = g._request_protected_instruction_approval(["AGENTS.md"], task_id="fixture")
    assert err is not None, "silêncio virou consentimento"
    assert "BLOCKED" in err and "no interactive user or gateway" in err


# ==========================================================================
# §3 — por que o estado próprio é necessário (controle POSITIVO do desenho)
# ==========================================================================

def test_c01_block_task_libera_claim_e_slot(conn):
    """C-01: bloquear solta claim/worker_pid — a parte que a pausa precisa reusar."""
    tid = _task(conn)
    kanban_db.recompute_ready(conn)
    assert kanban_db.claim_task(conn, tid) is not None
    assert kanban_db.get_task(conn, tid).status == "running"

    assert kanban_db.block_task(conn, tid, reason="espera", kind="needs_input") is True
    t = kanban_db.get_task(conn, tid)
    assert t.status == "blocked"
    assert t.claim_lock is None and t.claim_expires is None


def test_c02_bloqueio_repetido_escala_para_triage(conn):
    """C-02: é exatamente por isso que a espera humana NÃO pode reusar ``blocked``.

    Duas recorrências do mesmo kind levam a ``triage`` — demora humana viraria falha.
    """
    tid = _task(conn)
    for esperado in ("blocked", "triage"):
        kanban_db.recompute_ready(conn)
        t = kanban_db.get_task(conn, tid)
        if t.status == "blocked":
            kanban_db.unblock_task(conn, tid)
        kanban_db.recompute_ready(conn)
        assert kanban_db.claim_task(conn, tid) is not None
        kanban_db.block_task(conn, tid, reason="espera humana", kind="needs_input")
        assert kanban_db.get_task(conn, tid).status == esperado

    assert kanban_db.BLOCK_RECURRENCE_LIMIT == 2


def test_c07_recompute_ready_nao_promove_estado_de_espera_humana(conn):
    """C-07: a varredura de promoção não alcança ``waiting_approval`` nem ``scheduled``.

    Medido pelo comportamento: grava o estado direto na linha (o banco é temporário e
    o estado ainda não existe na API) e confere que a varredura o deixa parado. Se
    ``waiting_approval`` entrasse nessa varredura, a demora humana viraria respawn-loop.
    """
    tid = _task(conn)
    conn.execute("UPDATE tasks SET status='waiting_approval' WHERE id=?", (tid,))
    conn.commit()
    kanban_db.recompute_ready(conn)
    parado = conn.execute("SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0]
    assert parado == "waiting_approval", "a varredura promoveu uma espera humana"

    # Controle positivo da mesma varredura: um 'todo' sem pai pendente É promovido.
    outro = _task(conn)
    kanban_db.recompute_ready(conn)
    assert kanban_db.get_task(conn, outro).status == "ready", (
        "a varredura não promoveu nada — a fixture não mediu nada")


def test_c06_slot_conta_apenas_running(conn):
    """C-06 (precondição): o orçamento do dispatcher conta ``status='running'``.

    Logo, um estado próprio que não é ``running`` libera a vaga por construção.
    """
    from hermes_cli import kanban_db_dispatch as disp

    tid = _task(conn)
    kanban_db.recompute_ready(conn)
    kanban_db.claim_task(conn, tid)
    assert disp.count_running_tasks(conn) == 1

    kanban_db.schedule_task(conn, tid, reason="prova de que sair de running libera")
    assert disp.count_running_tasks(conn) == 0


# ==========================================================================
# §2 — payload e hash canônico
# ==========================================================================

def _request_hash(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_c11_request_hash_e_estavel_e_sensivel(tmp_path):
    """C-11: o hash canônico é estável à ordem das chaves e muda com o conteúdo."""
    alvo = tmp_path / "AGENTS.md"
    alvo.write_text("antes\n")
    pre = hashlib.sha256(alvo.read_bytes()).hexdigest()
    post = hashlib.sha256(b"depois\n").hexdigest()

    a = {"op": "write_file", "targets": [
        {"path_real": str(alvo), "pre_sha256": pre, "post_sha256": post}]}
    b = {"targets": [
        {"post_sha256": post, "pre_sha256": pre, "path_real": str(alvo)}], "op": "write_file"}
    assert _request_hash(a) == _request_hash(b), "hash dependeu da ordem das chaves"

    c = json.loads(json.dumps(a))
    c["targets"][0]["post_sha256"] = hashlib.sha256(b"outra coisa\n").hexdigest()
    assert _request_hash(c) != _request_hash(a), "hash não acusou mudança de conteúdo"


def test_c14_c15_revalidacao_recusa_preimagem_e_symlink_alterados(tmp_path):
    """C-14/C-15: a revalidação do §4 R-2 reprova preimagem trocada e symlink repontado.

    Implementa a regra como referência executável (a implementação real reusa esta lógica).
    """
    import os

    real = tmp_path / "real.md"
    real.write_text("original\n")
    link = tmp_path / "AGENTS.md"
    link.symlink_to(real)
    outro = tmp_path / "outro.md"
    outro.write_text("original\n")

    alvo = {
        "path_input": str(link),
        "path_real": os.path.realpath(str(link)),
        "is_symlink": True,
        "symlink_to": str(real),
        "pre_sha256": hashlib.sha256(real.read_bytes()).hexdigest()}

    def revalida(alvo: dict) -> bool:
        p = alvo["path_input"]
        if os.path.realpath(p) != alvo["path_real"]:
            return False
        if os.path.islink(p) != alvo["is_symlink"]:
            return False
        if os.path.islink(p) and os.path.realpath(os.readlink(p)) != os.path.realpath(alvo["symlink_to"]):
            return False
        atual = open(alvo["path_real"], "rb").read()
        return hashlib.sha256(atual).hexdigest() == alvo["pre_sha256"]

    assert revalida(alvo) is True  # controle POSITIVO

    real.write_text("alguem mexeu\n")
    assert revalida(alvo) is False, "preimagem alterada passou (C-14)"

    real.write_text("original\n")
    assert revalida(alvo) is True
    link.unlink()
    link.symlink_to(outro)
    assert revalida(alvo) is False, "symlink repontado passou (C-15)"


def test_c12_c13_consumo_e_uso_unico(tmp_path):
    """C-12/C-13: o CAS de consumo autoriza uma vez só — duplo clique e replay perdem."""
    db = sqlite3.connect(tmp_path / "j.db")
    db.execute(
        "CREATE TABLE approval_requests (request_id TEXT PRIMARY KEY, state TEXT NOT NULL, "
        "consumed_at INTEGER)")
    db.execute("INSERT INTO approval_requests VALUES ('r1', 'granted', NULL)")
    db.commit()

    def consome(rid: str) -> bool:
        cur = db.execute(
            "UPDATE approval_requests SET state='consumed', consumed_at=1 "
            "WHERE request_id=? AND state='granted' AND consumed_at IS NULL", (rid,))
        db.commit()
        return cur.rowcount == 1

    assert consome("r1") is True   # controle POSITIVO
    assert consome("r1") is False  # C-13: segundo clique não autoriza
    assert consome("r1") is False  # replay também não

    db.execute("INSERT INTO approval_requests VALUES ('r2', 'denied', NULL)")
    db.commit()
    assert consome("r2") is False, "decisão negada autorizou consumo (C-16)"
    db.close()


# ==========================================================================
# §3 — peças que AINDA NÃO existem (RED esperado, exigido pelo contrato)
# ==========================================================================

@pytest.mark.xfail(reason="contrato v2 §3 E-1: estado ainda não implementado", strict=True)
def test_c03_c04_estado_waiting_approval_existe():
    """C-03/C-04: estado próprio, válido mas nunca inicial."""
    assert "waiting_approval" in kanban_db.VALID_STATUSES
    assert "waiting_approval" not in kanban_db.VALID_INITIAL_STATUSES


@pytest.mark.xfail(reason="contrato v2 §3.4: journal ainda não migrado", strict=True)
def test_c09_journal_approval_requests_existe(conn):
    """C-09: a migração aditiva cria ``approval_requests`` em board novo e antigo."""
    tabelas = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "approval_requests" in tabelas


# ==========================================================================
# v2 — critérios novos, exigidos pela devolução R1
# ==========================================================================

def test_c08_as_cinco_varreduras_de_reciclagem_so_alcancam_running(conn):
    """C-08: as CINCO varreduras de reciclagem só varrem ``running``.

    Contrato v3 §3.2 E-7, §0.2 e §4.3 R-5.1 dependem disto: um card em
    ``waiting_approval`` (sem ``worker_pid``, sem claim) não pode ser reciclado nem
    promovido a ``ready`` por nenhuma delas, senão a demora humana vira respawn com LLM.

    A v2 dizia TRÊS varreduras e citava uma linha errada. São cinco, medidas aqui:
    ``detect_stale_running``, ``reconcile_orphaned_running``, ``detect_crashed_workers``
    (via ``_reclaim_dead_workers``), ``enforce_max_runtime`` e ``release_stale_claims``.
    Duas delas (``reconcile_orphaned_running``, ``enforce_max_runtime``) nunca tinham
    sido executadas por fixture nenhuma.

    Medido pelo COMPORTAMENTO: grava o estado direto na linha (a API ainda não o tem),
    roda as cinco e confere que a linha não se moveu. Controle POSITIVO na mesma
    medição: uma task realmente ``running`` e vencida É reciclada.
    """
    from hermes_cli import kanban_db_dispatch as disp

    parado = _task(conn)
    conn.execute(
        "UPDATE tasks SET status='waiting_approval', worker_pid=NULL, claim_lock=NULL, "
        "claim_expires=NULL, last_heartbeat_at=NULL, max_runtime_seconds=1 WHERE id=?",
        (parado,))

    # Controle positivo: esta SIM deve ser reciclada (running, claim vencido, sem heartbeat).
    vivo = _task(conn)
    kanban_db.recompute_ready(conn)
    assert kanban_db.claim_task(conn, vivo) is not None
    conn.execute(
        "UPDATE tasks SET claim_expires = 1, started_at = 1, last_heartbeat_at = NULL, "
        "worker_pid = NULL WHERE id=?", (vivo,))
    conn.execute("UPDATE task_runs SET started_at = 1 WHERE task_id = ?", (vivo,))
    conn.commit()

    # As CINCO. Nenhuma pode tocar em `parado`.
    disp.detect_stale_running(conn, stale_timeout_seconds=1)
    disp.reconcile_orphaned_running(conn)
    disp.detect_crashed_workers(conn)
    disp.enforce_max_runtime(conn)
    kanban_db.release_stale_claims(conn)

    assert conn.execute(
        "SELECT status FROM tasks WHERE id=?", (parado,)).fetchone()[0] == "waiting_approval", (
        "uma varredura de reciclagem moveu uma espera humana")
    assert conn.execute(
        "SELECT status FROM tasks WHERE id=?", (vivo,)).fetchone()[0] != "running", (
        "nenhuma varredura reciclou o controle positivo — a fixture não mediu nada")


def test_c36_a_volta_a_running_precisa_restaurar_a_identidade_no_mesmo_cas(conn):
    """C-36 (bloqueador R2 #1): ``running`` sem claim é reciclado para ``ready``.

    Contrato v3 §3.2 E-9. A pausa (E-3) zera ``claim_lock``/``worker_pid``/heartbeat.
    Se a retomada devolvesse o card a ``running`` mexendo SÓ no status,
    ``reconcile_orphaned_running`` (``kanban_db_dispatch.py:851-855``) o promoveria a
    ``ready`` — e o dispatcher faria ``Popen`` de um SEGUNDO worker LLM ao lado do
    primeiro, que continua vivo. Seria a regeneração que R-3 proíbe.

    A fixture mede os DOIS lados na mesma execução, que é o que a torna uma medição e
    não uma afirmação:

    * controle POSITIVO — ``running`` + claim NULL (a forma ERRADA de retomar) É
      reciclado para ``ready``. Prova que o perigo é real, não hipotético.
    * a forma EXIGIDA por E-9 — status e identidade no mesmo UPDATE — NÃO é reciclada.
    """
    from hermes_cli import kanban_db_dispatch as disp

    # --- controle positivo: a forma ERRADA (só o status) ---
    errado = _task(conn)
    conn.execute(
        "UPDATE tasks SET status='running', claim_lock=NULL, claim_expires=NULL, "
        "worker_pid=NULL, worker_started_at=NULL, last_heartbeat_at=NULL WHERE id=?",
        (errado,))
    conn.commit()

    disp.reconcile_orphaned_running(conn)
    assert conn.execute(
        "SELECT status FROM tasks WHERE id=?", (errado,)).fetchone()[0] == "ready", (
        "controle positivo falhou: reconcile_orphaned_running não reciclou "
        "running+claim NULL — a premissa de E-9 mudou, reavaliar o contrato")

    # --- a forma EXIGIDA por E-9: status + identidade no MESMO UPDATE ---
    certo = _task(conn)
    kanban_db.recompute_ready(conn)
    assert kanban_db.claim_task(conn, certo) is not None
    lock, pid, fingerprint = kanban_db._claimer_id(), os.getpid(), "|17899999999"
    agora = int(__import__("time").time())
    # Simula a pausa (E-3) e a retomada (E-9) numa sentença só.
    conn.execute(
        "UPDATE tasks SET status='waiting_approval', claim_lock=NULL, claim_expires=NULL, "
        "worker_pid=NULL, worker_started_at=NULL, last_heartbeat_at=NULL WHERE id=?", (certo,))
    cur = conn.execute(
        "UPDATE tasks SET status='running', claim_lock=?, claim_expires=?, worker_pid=?, "
        "worker_started_at=?, last_heartbeat_at=? "
        "WHERE id=? AND status='waiting_approval'",
        (lock, agora + 3600, pid, fingerprint, agora, certo))
    conn.commit()
    assert cur.rowcount == 1, "o CAS de E-9 não alcançou a linha — medição inválida"

    disp.reconcile_orphaned_running(conn)
    assert conn.execute(
        "SELECT status FROM tasks WHERE id=?", (certo,)).fetchone()[0] == "running", (
        "E-9: com claim/PID restaurados no mesmo CAS, a varredura de órfãs não pode "
        "reciclar a task retomada")


def test_c37_predicado_unico_de_orfa_alcanca_consumed_nao_aplicada(tmp_path):
    """C-37 (bloqueador R2 #2): um predicado, um destino.

    Contrato v3 §4.4 R-7. A v2 só alcançava ``pending``/``granted``; uma request
    ``consumed`` cujo worker morreu antes de escrever não era vista por ninguém e o
    card ficava preso em ``waiting_approval`` para sempre (sem worker, sem varredura,
    sem saída humana: E-8 recusa verbo genérico e U-7 não re-decide ``consumed``).

    v3 usa ``applied_at IS NULL AND state IN ('pending','granted','consumed')``. A
    fixture roda o predicado contra o DDL de §3.4 e confere que ele:
      * ALCANÇA as três não-aplicadas (a ``consumed`` inclusive — era o buraco);
      * NÃO alcança a aplicada (``applied_at`` preenchido), senão reabriria o caso feliz;
      * NÃO alcança os terminais humanos (``denied``/``cancelled``/``obsolete``).
    """
    db = sqlite3.connect(tmp_path / "orfas.db")
    db.execute(
        "CREATE TABLE approval_requests (request_id TEXT PRIMARY KEY, state TEXT NOT NULL, "
        "applied_at INTEGER)")
    db.executemany(
        "INSERT INTO approval_requests VALUES (?,?,?)",
        [("r_pend", "pending", None),
         ("r_grant", "granted", None),
         ("r_cons", "consumed", None),        # o buraco de R2 #2
         ("r_aplicada", "consumed", 1789920000),
         ("r_deny", "denied", None),
         ("r_cancel", "cancelled", None),
         ("r_obsolete", "obsolete", None)])
    db.commit()

    orfas = {r[0] for r in db.execute(
        "SELECT request_id FROM approval_requests "
        " WHERE applied_at IS NULL AND state IN ('pending','granted','consumed')")}

    assert orfas == {"r_pend", "r_grant", "r_cons"}, (
        f"predicado de R-7 não é único/exato: {sorted(orfas)}")
    assert "r_cons" in orfas, "R2 #2: consumed-sem-escrita ficaria preso de novo"
    assert "r_aplicada" not in orfas, "a operação aplicada não pode voltar à varredura"
    db.close()


def test_c31_regiao_critica_serializa_entre_processos(tmp_path):
    """C-31: o consumo+escrita precisa de lock CROSS-PROCESS (contrato v2 §4.2 R-2.1).

    Mede os dois lados na mesma execução:

    1. ``tools.file_state.lock_path`` é intra-processo — dois processos o tomam
       ao mesmo tempo sem se bloquear. Isso é fato medido, não opinião, e é por
       isso que o contrato exige ``flock`` por cima dele.
    2. ``fcntl.flock(LOCK_EX)`` (o padrão já usado em ``tools/mcp_tool_loop.py``)
       serializa de verdade: o segundo processo não entra enquanto o primeiro segura.
    """
    prog = textwrap.dedent(
        """
        import fcntl, os, sys, time
        modo, lockfile, marcador = sys.argv[1], sys.argv[2], sys.argv[3]
        if modo == "threadlock":
            sys.path.insert(0, os.environ["REPO"])
            from tools import file_state
            with file_state.lock_path(lockfile):
                open(marcador, "a").write("entrou\\n")
                time.sleep(0.6)
            sys.exit(0)
        fh = open(lockfile, "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            sys.exit(7)            # não entrou: o outro processo segura o lock
        open(marcador, "a").write("entrou\\n")
        time.sleep(0.6)
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        """
    )
    script = tmp_path / "disputa.py"
    script.write_text(prog)
    env = {**os.environ, "REPO": os.getcwd()}

    # (1) lock de thread: ambos entram — prova de que NÃO serve entre processos.
    alvo_t, marca_t = str(tmp_path / "t.txt"), str(tmp_path / "mt.txt")
    a = subprocess.Popen([sys.executable, str(script), "threadlock", alvo_t, marca_t], env=env)
    b = subprocess.Popen([sys.executable, str(script), "threadlock", alvo_t, marca_t], env=env)
    assert a.wait(timeout=30) == 0 and b.wait(timeout=30) == 0
    entraram_thread = open(marca_t).read().count("entrou")
    assert entraram_thread == 2, (
        "o lock de thread bloqueou entre processos — então a premissa de R-2.1 mudou "
        f"(entraram={entraram_thread}); reavaliar o contrato antes de implementar")

    # (2) flock: só um entra — controle POSITIVO do mecanismo exigido.
    alvo_f, marca_f = str(tmp_path / "f.lock"), str(tmp_path / "mf.txt")
    c = subprocess.Popen([sys.executable, str(script), "flock", alvo_f, marca_f], env=env)
    import time as _t
    _t.sleep(0.15)  # garante que c já pegou o lock antes de d tentar
    d = subprocess.Popen([sys.executable, str(script), "flock", alvo_f, marca_f], env=env)
    rc_c, rc_d = c.wait(timeout=30), d.wait(timeout=30)
    assert {rc_c, rc_d} == {0, 7}, f"flock não serializou: rc={(rc_c, rc_d)}"
    assert open(marca_f).read().count("entrou") == 1, "dois processos entraram sob flock"


def test_c32_saida_de_waiting_approval_por_verbo_generico_ainda_e_possivel(conn):
    """C-32 (RED de v2 §3.2 E-8): hoje o UPDATE direto do dashboard não olha a ORIGEM.

    ``_set_status_direct`` (``plugin_api.py:703-731``) faz ``UPDATE tasks SET status=?``
    sem cláusula sobre o status atual. Enquanto E-8 não for implementado, arrastar um
    card de ``waiting_approval`` para ``ready`` sai da espera sem consumir grant.

    A fixture reproduz a forma do UPDATE nativo contra a tabela real — não importa o
    módulo do dashboard (que exige fastapi) — e falha quando a guarda de origem existir,
    hora de trocar este xfail pelo positivo.
    """
    tid = _task(conn)
    conn.execute("UPDATE tasks SET status='waiting_approval' WHERE id=?", (tid,))
    conn.commit()

    # Exatamente a forma da guarda que o contrato EXIGE (E-8, camada 1).
    cur = conn.execute(
        "UPDATE tasks SET status='ready' WHERE id=? AND status != 'waiting_approval'", (tid,))
    conn.commit()
    assert cur.rowcount == 0, "guarda de origem funcionou na forma exigida por E-8"

    # E a forma ATUAL do nativo (sem guarda de origem) ainda deixa escapar: é o RED.
    cur = conn.execute("UPDATE tasks SET status='ready' WHERE id=?", (tid,))
    conn.commit()
    assert cur.rowcount == 1, "o UPDATE sem guarda não alcançou a linha — medição inválida"
    assert conn.execute(
        "SELECT status FROM tasks WHERE id=?", (tid,)).fetchone()[0] == "ready", (
        "RED de C-32: sem E-8, o verbo genérico tira o card da espera humana")


def test_c33_uma_pendencia_por_run_e_constraint_do_banco(tmp_path):
    """C-33: o índice único parcial de §2.1/§3.4 rejeita a segunda ``pending``.

    Referência executável do DDL: se o índice ficar de fora da migração, duas filas
    humanas para o mesmo run passam a existir e o contador de §5 U-3 mente.
    """
    db = sqlite3.connect(tmp_path / "j.db")
    db.execute(
        "CREATE TABLE approval_requests (request_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, "
        "run_id INTEGER NOT NULL, state TEXT NOT NULL)")
    db.execute(
        "CREATE UNIQUE INDEX idx_appr_one_pending_per_run "
        "ON approval_requests(task_id, run_id) WHERE state = 'pending'")
    db.execute("INSERT INTO approval_requests VALUES ('r1','t1',1,'pending')")
    db.commit()

    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO approval_requests VALUES ('r2','t1',1,'pending')")
        db.commit()
    db.rollback()

    # Controles POSITIVOS: outro run pode; e uma decidida libera nova pendência no mesmo run.
    db.execute("INSERT INTO approval_requests VALUES ('r3','t1',2,'pending')")
    db.execute("UPDATE approval_requests SET state='consumed' WHERE request_id='r1'")
    db.execute("INSERT INTO approval_requests VALUES ('r4','t1',1,'pending')")
    db.commit()
    # r1 saiu para 'consumed'; restam r3 (run 2) e r4 (run 1) pendentes.
    assert db.execute(
        "SELECT COUNT(*) FROM approval_requests WHERE state='pending'").fetchone()[0] == 2
    assert db.execute(
        "SELECT COUNT(*) FROM approval_requests").fetchone()[0] == 3, "nada foi apagado"
    db.close()


@pytest.mark.xfail(
    reason="contrato v3 §5 U-4: 'approval_requested' ainda não é kind notificável", strict=True)
def test_c35_approval_requested_e_notificavel_nas_duas_listas():
    """C-35: o aviso da origem depende das DUAS listas espelhadas.

    ``gateway/kanban_watchers_notifier.py:36`` (``TERMINAL_KINDS``) e o espelho
    ``tui_gateway/session_notifications.py:136`` (``_KANBAN_NOTIFY_KINDS``). Se só uma
    ganhar o kind, o aviso sai numa superfície e some na outra — e U-5 diz que aviso
    não entregue não autoriza nada.

    Em v2 esta fixture afirmava SÓ a lista do gateway, então implementar metade de U-4
    a deixaria verde — o defeito que o revisor apontou em R2. v3 afirma as duas.

    Registrado (contrato §5 U-4.1): as listas JÁ divergem hoje em três kinds
    (``block_loop_detected``/``review_requested``/``changes_requested``, só no gateway).
    Essa dívida preexistente NÃO é escopo deste contrato e não é asseverada aqui; a
    fixture mede apenas o kind desta feature nas duas pontas.
    """
    from gateway import kanban_watchers_notifier as gw
    from tui_gateway import session_notifications as tui

    faltando = [nome for nome, lista in (
        ("gateway.TERMINAL_KINDS", set(gw.TERMINAL_KINDS)),
        ("tui._KANBAN_NOTIFY_KINDS", set(tui._KANBAN_NOTIFY_KINDS)),
    ) if "approval_requested" not in lista]
    assert not faltando, f"'approval_requested' ausente em: {faltando}"
