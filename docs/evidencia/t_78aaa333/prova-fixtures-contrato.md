# Evidência de execução — fixtures do contrato v2 (t_069cfdac, run 539)

Ambiente: Docker **não-root** (UID 502), `--network none`, imagem de dependências já
existente `kanban-body-t5a6:proof` (NÃO reconstruída). Fonte regenerada com
`git archive HEAD` em diretório temporário novo; a fixture foi copiada para
`tests/tools/` apenas dentro do lab. Runner obrigatório `scripts/run_tests.sh`
(sem `pytest` puro). `HOME` isolado, `HERMES_TEST_ISOLATION=1`,
`HERMES_PYTHON=/usr/local/bin/python3`.

Nada foi alterado na árvore de trabalho fora de `docs/evidencia/t_78aaa333/`.

## 0. O que mudou em relação à prova de v1

- **C-24 deixou de ser skip.** Em v1 a fixture pulava por falta de `fastapi` no lab.
  Aqui as dependências do dashboard (`fastapi`, `starlette`, `multipart`,
  `python_multipart`, `annotated_doc`) são montadas de `read-only` do venv do host
  direto no `site-packages` do container. `PYTHONPATH` **não** funciona: `run_tests.sh`
  roda o runner sob `env -i` (linhas 174-188) e derruba a variável — por isso a montagem
  é no `site-packages`, não na env.
- **O mutante 3 (verbo `approve` no PATCH genérico), que v1 não mediu, foi medido e morto.**
- Três mutantes novos/corrigidos: M1 reescrito (a âncora de v1 mutava outra função e por
  isso teria sobrevivido — documentado abaixo), M4 novo para C-35.
- 4 critérios novos do contrato v2 entraram na medição: C-08, C-31, C-32, C-33, C-35.

Script de mutação versionado junto: `fixtures/mutar.py` (aplicado numa CÓPIA da fonte,
nunca na árvore real).

## 1. Baseline (código íntegro)

    Discovered 1 test files (~19 tests) under ['tests/tools/test_contrato_aprovacao.py']; running with -j 28
    [100.0% |    19/~19 | ✓16 | ✗ 0] ✓ tests/tools/test_contrato_aprovacao.py (16✓ 3xf, 4.8s)

    === Summary: 1 files, 16 tests passed, 0 failed (100% complete) in 4.8s (28 workers) ===

- **16 passaram**: precondições do contrato que valem hoje.
- **3 `xfail` estritos**: `C-03/C-04` (estado `waiting_approval`), `C-09` (tabela
  `approval_requests`) e `C-35` (`approval_requested` notificável). São o RED do que falta;
  `strict=True` faz um xpass silencioso virar falha, então implementar sem avisar acusa.
- **0 pulados.** Era 1 em v1 (C-24).

Nota de honestidade sobre o RED de C-32: ele **não** é xfail. A fixture mede as duas formas
do UPDATE lado a lado — a guarda de origem exigida por E-8 (que já funciona quando escrita)
e a forma atual do nativo (sem guarda, que deixa o card escapar). O RED está na segunda
asserção e é positivo hoje: enquanto E-8 não existir, ela documenta o buraco sem quebrar o
run. Quando E-8 for implementado, o teste da implementação (`I`) é que fecha o critério.

## 2. Controle negativo — quatro mutantes, quatro mortos

### Mutante 1 — "adicionar o estado novo à varredura de promoção"

Simula o erro que o contrato v2 §3.2 E-5 proíbe: `recompute_ready` passa a varrer **e**
promover `waiting_approval`, convertendo demora humana em respawn-loop. Quebra as duas
camadas (o `SELECT` de `kanban_db.py:2145` e a guarda `AND status = 'todo'` do `UPDATE`
em `:2178`).

    E       AssertionError: a varredura promoveu uma espera humana
    tests/tools/test_contrato_aprovacao.py:203: AssertionError
    E       AssertionError: uma varredura de reciclagem moveu uma espera humana
    tests/tools/test_contrato_aprovacao.py:379: AssertionError
    FAILED tests/tools/test_contrato_aprovacao.py::test_c07_recompute_ready_nao_promove_estado_de_espera_humana
    FAILED tests/tools/test_contrato_aprovacao.py::test_c08_varreduras_de_reciclagem_so_alcancam_running
    === Summary: 1 files, 14 tests passed, 2 failed (100% complete) in 8.3s (28 workers) ===

**MORTO**, por duas fixtures independentes (C-07 e C-08).

**Falha honesta registrada:** a primeira versão deste mutante nesta rodada usava a âncora
`"todo", "blocked"` (aspas duplas, sintaxe Python) e mutou **outra função**
(`kanban_db.py:3441`), não o SQL de `recompute_ready` — e o run passou 16/16, ou seja, o
mutante teria sido reportado como "sobreviveu" por erro do script de mutação, não por
fraqueza da fixture. Corrigido para ancorar no SQL literal (aspas simples). Fica registrado
porque um mutante mal ancorado é exatamente o jeito de fabricar confiança falsa nos dois
sentidos.

### Mutante 2 — "o portão protegido passa a honrar yolo"

Insere um atalho `if is_session_yolo_enabled(...): return None` em
`_request_protected_instruction_approval`, transformando o portão de arquivo protegido
em "mais um gate".

    E           AssertionError: yolo liberou escrita em arquivo protegido
    tests/tools/test_contrato_aprovacao.py:123: AssertionError
    FAILED tests/tools/test_contrato_aprovacao.py::test_c26_portao_protegido_ignora_yolo_enquanto_o_gate_comum_o_honra
    === Summary: 1 files, 15 tests passed, 1 failed (100% complete) in 8.3s (28 workers) ===

**MORTO.** A mesma fixture carrega controle positivo: o gate comum (`~/.ssh/config`) libera
sob yolo no mesmo estado, então a medição distingue os dois portões em vez de só verificar
que "algo bloqueou".

### Mutante 3 — "o PATCH genérico do dashboard ganha verbo `approve`"

Era o **NÃO MEDIDO** de v1. Acrescenta `"approve"` a `_STATUS_HANDLERS`
(`plugins/kanban/dashboard/plugin_api.py`), que é exatamente a porta que §1.2 A-3 proíbe.

    E       AssertionError: verbo de decisão exposto no PATCH genérico: {'approve'}
    tests/tools/test_contrato_aprovacao.py:84: AssertionError
    FAILED tests/tools/test_contrato_aprovacao.py::test_c24_patch_generico_do_dashboard_nao_tem_verbo_de_aprovacao
    === Summary: 1 files, 15 tests passed, 1 failed (100% complete) in 8.5s (28 workers) ===

**MORTO.** Medição real com o módulo do dashboard importado, não por leitura de fonte nem AST.

### Mutante 4 — "o aviso entra só numa das duas listas"

`approval_requested` entra em `TERMINAL_KINDS` do gateway
(`gateway/kanban_watchers_notifier.py:36`) **sem** o espelho de
`tui_gateway/session_notifications.py:134` — exatamente a assimetria que §5 U-4 proíbe.

    [XPASS(strict)] contrato v2 §5 U-4: 'approval_requested' ainda não é kind notificável
    FAILED tests/tools/test_contrato_aprovacao.py::test_c35_approval_requested_e_notificavel_nas_duas_listas
    === Summary: 1 files, 16 tests passed, 1 failed (100% complete) in 9.7s (28 workers) ===

**MORTO** pelo `strict=True`: implementar metade do U-4 quebra o run em vez de passar
silenciosamente.

## 3. C-31 — a medição que corrige uma premissa errada de v1

A v1 mandava revalidar "dentro do mesmo lock de path já existente
(`file_state.lock_path`)". Medido aqui com **dois processos reais**:

- `tools.file_state.lock_path` é um `threading.Lock` num registro de processo
  (`tools/file_state.py:66-95`): os dois processos entram ao mesmo tempo
  (`entraram=2`). Entre processos ele **não protege nada** — era TOCTOU com aparência de
  guarda.
- `fcntl.flock(LOCK_EX)` — o padrão que o repositório já usa em
  `tools/mcp_tool_loop.py:44-60` — serializa: um processo entra (`rc=0`), o outro é
  recusado (`rc=7`), marcador com uma única entrada.

Por isso o contrato v2 §4.2 R-2.1 exige `flock` por cima do `lock_path`, e não no lugar
dele. A fixture também falha se a premissa mudar (se um dia `lock_path` virar cross-process,
ela manda reavaliar o contrato antes de implementar).

## 4. O que NÃO foi medido, e por quê

- **Entrega real de aviso (C-21/C-22), UI instalada (C-19/C-28/C-29):** fora do alcance
  de fixture, por construção. São `I`/`H` na matriz do contrato.
- **Espera longa real (C-18/C-30):** fixture com relógio controlado é aproximação; a prova
  honesta é a etapa 7 do plano.
- **Órfã por morte de worker (C-34):** precisa de processo real morrendo no meio de uma
  pendência; é `I` na implementação, não precondição de hoje.
- **Isolamento contra processo hostil de mesmo UID (§1.3, Camada 2):** não medido e
  **não prometido**. O worker e a superfície humana compartilham UID 502 e o mesmo
  `kanban.db` (`-rw-r--r-- farantes staff`, medido).
- **Nenhum dos 16 verdes prova a feature pronta.** Provam precondições e guardas de fluxo:
  o que existe hoje, o que ainda não existe (RED estrito), e o que as portas genéricas
  fazem quando alguém tenta usá-las para decidir.

## 5. Limpeza

Containers do lab removidos ao fim; nenhuma imagem foi construída ou apagada. As
dependências do dashboard foram montadas read-only a partir do venv do host — nada foi
instalado dentro da imagem e a rede ficou desligada (`--network none`) em todas as
execuções.
