# Contrato executável — aprovação humana persistente para operações de worker Kanban

Versão: **v2** (v1 devolvida pelo revisor em R1; esta versão fecha os 4 bloqueadores de miolo).
Autor: arquiteto (t_069cfdac). Revisor exigido: CISO/QA independente, nunca o autor.
Norma: CYTRACKS-SDD v4.0-RC, 317 linhas, SHA-1 `8fc4a63af6144b81546f223e2dd5f23c038f5c4c`
(lido do objeto Git `origin/main:specops/CYTRACKS-SDD-v4.0-RC.md`, reconferido neste run).

Rota efetiva do autor: `anthropic` / `claude-opus-5`, credencial OAuth em
`~/.hermes/profiles/arquiteto/auth.json` (`-rw-------`, chaves `oauth`/`auth_type` presentes).
Sem API paga por token, sem wrapper ask-*/dev-*. Mesma família do revisor é permitida; não se
alega diversidade.

## 0. O que este documento é e o que não é

É o contrato técnico que faltava para t_78aaa333 sair de bloqueio: define QUEM aprova,
O QUE está autorizado, COMO a espera persiste, QUEM materializa a escrita e COMO a operação
retoma. Um leitor implementa a partir daqui sem redefinir autoria nem conteúdo autorizado.

NÃO é: rollout, homologação de UI, aprovação de UX (já dada pelo H1), nem autorização
para escrever em AGENTS/SOUL. NÃO promove `rascunho-sincrono-nao-integrado.tar.gz`
(código incompleto, não executado).

Todas as referências de código abaixo foram lidas neste worktree
(`/Users/farantes/atlas/wt/kanban-aprovacao-interativa`, branch
`executor/kanban-aprovacao-interativa`, base `d7ea741ae04`). Nada foi alterado fora de
`docs/evidencia/t_78aaa333/`.

### 0.1 O que mudou de v1 para v2 (rastreabilidade da devolução R1)

| Bloqueador R1 | Onde foi resolvido | Resumo da mudança |
|---|---|---|
| 1. Retomada sem ator nativo | §4.0 (novo), §3.2 E-3/E-4, §6 etapa 4 | O ator que materializa a escrita é o **próprio worker vivo**, que NÃO morre na pausa: a guarda bloqueia na thread da ferramenta e o processo continua existindo. `approve` **não** volta a `ready` nem respawna LLM. |
| 2. Identidade §2.1 ≠ DDL §3.4 | §2.1, §3.4 | `board` declarado implícito (1 DB por board, medido) e REMOVIDO da lista NOT NULL; `created_by_pid`/`created_by_started_at` entram no DDL como NOT NULL; índice único parcial de uma pending por run. |
| 3. Saída genérica de `waiting_approval` | §3.2 E-8 (novo), §5 U-7 | `_drag_to`/`_set_status_direct`/bulk recusam origem `waiting_approval` por guarda explícita de status de origem no UPDATE; único caminho de saída é o endpoint de decisão. |
| 4. Crash vs stale + revalidação fora do lock | §4.2, §4.4 R-5, §3.2 E-7 | Consumo + revalidação + escrita numa única região crítica com **lock de arquivo cross-process** (`fcntl.flock`, o `lock_path` atual é só intra-processo — medido); crash pós-consumo deixa `consumed` e o card em `blocked`, e o worker morto é reciclado por `detect_stale_running` **sem** reabrir a request. |
| C-24 não medido | §7, `prova-fixtures-contrato.md` §3 | `fastapi` injetado no lab por PYTHONPATH; C-24 medido e mutante 3 morto. |

## 1. Fronteira de autoria — quem aprova, e contra o quê isso protege

### 1.1 Superfícies humanas reais que existem hoje

| Superfície | Como a decisão entra | Onde vive |
|---|---|---|
| Gateway/Desktop/TUI | `approval.respond` (JSON-RPC) → `tools.approval.resolve_gateway_approval(session_key, choice)` | `tui_gateway/methods_prompt.py:1235+`, `tools/approval.py:138` |
| CLI interativo | callback por thread `tools.terminal_tool._get_approval_callback()` | `tools/file_tools_write_guards.py:307-318` |
| Messaging gateway | `/approve` / `/deny` antes das duas guardas de mensagem | `gateway/run_busy.py` |

O estado dessas filas (`tools/approval.py:118-119`: `_gateway_queues`, `_gateway_notify_cbs`)
é **em memória, do processo que detém o canal humano**. O worker Kanban é outro processo
(`hermes_cli/kanban_db_dispatch.py:2844`, `stdin=DEVNULL`), então hoje ele não tem canal:
`file_tools_write_guards.py:313-316` falha fechado com `_NO_HUMAN`. Esse é o RED já
reproduzido (`UI=None request_id=ABSENT`, timeout 1,102s).

### 1.2 Regra de autoria (normativa)

**A-1.** A decisão humana é autoritativa **somente** quando produzida no processo que detém
a superfície humana viva (serve/desktop/TUI/gateway/CLI) e entregue pelo transporte nativo
existente (`approval.respond` / callback CLI / `/approve`) ou pelo endpoint de decisão do
dashboard (§5 U-7). Nenhuma outra porta cria decisão.

**A-2.** O registro persistido da decisão (§3) é **prova de auditoria e canal de transporte
entre processos, não fonte de autoridade de execução**. O consumidor revalida o payload
(§2, §4) antes de escrever; uma linha de decisão sem preimagem coincidente não autoriza nada.

**A-3.** Portas explicitamente proibidas como aceite técnico, cada uma com o ponto de código
que precisa recusar:
- comentário/chat no card (`kanban_db.add_comment`, `hermes_cli/kanban_db.py:1762`) — medido
  hoje: só INSERT, não toca `tasks.status`;
- `PATCH /tasks/{id}` do dashboard e `POST /tasks/bulk`
  (`plugins/kanban/dashboard/plugin_api.py:551-571`, `_STATUS_HANDLERS`): a decisão de
  aprovação **não** entra como verbo de status genérico — medido hoje, os verbos são
  exatamente `{blocked, done, ready, review, scheduled, todo, triage}`;
- **sair de `waiting_approval` por qualquer verbo genérico** (drag, PATCH, bulk) — ver §3.2 E-8,
  que é a recusa nova exigida por este contrato (hoje `_set_status_direct`,
  `plugin_api.py:703-731`, faz UPDATE sem guarda de status de ORIGEM);
- qualquer ferramenta do toolset `kanban` do worker (`tools/kanban_tools_schemas.py`:
  `kanban_show/list/complete/block/request_review/request_changes/heartbeat/comment/
  attach/attach_url/attachments/create/unblock/link`) — nenhuma ganha poder de decidir;
- toggle de configuração, allowlist para protegidos, autoapprove, grant de sessão/global.
  `file_tools_write_guards.py:254-260` já documenta que este portão não passa por
  `_run_approval_gate` (não honra `--yolo` nem allowlist): **isso se preserva**.

**A-4.** O agente nunca clica pelo H1. Proibido usar ferramenta de GUI/browser para
responder a própria aprovação.

### 1.3 Modelo de ameaça — medido, não desenhado

MEDIDO neste host: `~/.hermes/kanban/boards/atlas/kanban.db` é `-rw-r--r-- farantes staff`,
UID 502; o worker Kanban roda sob o **mesmo UID** e tem ferramenta de terminal.

Consequência honesta, em duas camadas:

- **Camada 1 — protegida por este contrato (erro e uso indevido do fluxo):** o worker não
  tem ferramenta, endpoint, nem caminho documentado para aprovar; toda porta genérica recusa
  (A-3 + E-8); o consumo revalida preimagem (§4). Um agente que "acha" que foi aprovado não
  escreve. Isto é verificável por fixture.
- **Camada 2 — NÃO protegida, e não se promete o contrário (processo hostil de mesmo UID
  com shell):** um processo sob UID 502 pode abrir o SQLite e inserir uma linha de decisão,
  ou reescrever o arquivo alvo direto pelo shell, sem passar por guarda nenhuma. Nenhum
  desenho dentro deste UID fecha isso. **Não há sandbox a prometer.**

Corolário de desenho: **não aumente a superfície da Camada 2** — em particular, não exponha
uma porta de resposta acessível ao worker, mesmo "só para testes" (a sonda JSON-RPC anterior
foi recusada pelo scanner e não deve ser repetida nem contornada).

### 1.4 Risco residual que exige decisão do H1 (fato + opções, sem bloqueio abstrato)

Fato: a Camada 2 permanece aberta porque worker e superfície humana compartilham UID 502 e
o mesmo `kanban.db`. Opções concretas:

- **(a) Aceitar o risco residual** (recomendada para esta frente). Custo: 0. Risco: um
  processo hostil de mesmo UID escreve sem aprovação — mas esse processo já podia editar o
  arquivo alvo direto; a aprovação não era a barreira que o impedia. Mitigação: auditoria
  de decisão (§3.4) torna a fabricação detectável a posteriori.
- **(b) Autoridade fora do UID:** daemon de decisão sob usuário próprio, socket com
  permissão de grupo. Custo alto (instalação, privilégio, ciclo de vida, matriz de SO);
  fora do recorte atual.
- **(c) Assinatura da decisão com chave no Keychain sob ACL biométrica.** Custo médio,
  macOS-específico, e o worker de mesmo UID ainda pode reescrever o arquivo alvo por fora —
  ou seja, eleva o custo de forjar a decisão sem fechar a Camada 2.

Recomendação do autor: **(a)**, registrando o limite no próprio contrato. Decisão é do H1;
enquanto não houver decisão, vale (a) com o limite declarado — a implementação de §2–§6 não
depende dessa escolha.

## 2. Identidade e payload imutável

### 2.1 Identidade da solicitação (`approval_request`)

Chave primária: `request_id` (hex 32, gerado pelo processo do worker no momento em que a
guarda dispara; o formato reaproveita `uuid.uuid4().hex` de `tools/approval_gateway_wait.py`).

**Board é implícito, não uma coluna.** MEDIDO: `kanban_db.kanban_db_path()`
(`hermes_cli/kanban_db.py:507-510`) resolve **um arquivo `kanban.db` por board**, e o
dispatcher injeta `HERMES_KANBAN_DB` / `HERMES_KANBAN_BOARD` no worker
(`kanban_db_dispatch.py:2816-2822`). Logo, uma linha desta tabela já pertence ao board do
arquivo em que está; uma coluna `board` seria um segundo índice de nome, capaz de divergir do
arquivo (o mesmo erro que `AGENTS.md` de `plugins/` chama de "segundo índice de nome").
Onde o board precisa aparecer para o humano (contador §5 U-3, aviso §5 U-4), ele vem do
resolvedor de board da superfície (`_resolve_board`, `plugin_api.py:65-73`), não da linha.

Correlação obrigatória — esta lista e o DDL de §3.4 são **a mesma lista**, campo a campo:

| Campo | Nulabilidade | Origem medida |
|---|---|---|
| `request_id` | PK | `uuid4().hex` no worker |
| `task_id` | NOT NULL | `HERMES_KANBAN_TASK` |
| `run_id` | NOT NULL | `tasks.current_run_id` / `HERMES_KANBAN_RUN_ID` — a solicitação pertence ao run |
| `claim_lock` | NOT NULL | `tasks.claim_lock` no instante da criação (`_claimer_id()`, `kanban_db.py:1086`); prova que quem pediu detinha o claim |
| `profile_home` | NOT NULL | caminho absoluto do `HERMES_HOME` do perfil (não o nome: um processo serve vários perfis) |
| `session_key` | NOT NULL | `tools/approval_context.get_current_session_key` |
| `workspace_path` | NOT NULL | `tasks.workspace_path` resolvido |
| `created_by_pid` | NOT NULL | `os.getpid()` do worker |
| `created_by_started_at` | NOT NULL | fingerprint do PID, o mesmo par de `_worker_alive` (`kanban_db_dispatch.py:375`) |
| `origin_session` | NULL permitido | sessão/conversa de origem do card, para o aviso do §5; cards criados sem origem persistida não têm |
| `created_at` | NOT NULL | `int(time.time())` |

**U-3 (uma pending por run) é constraint, não prosa:**
`CREATE UNIQUE INDEX IF NOT EXISTS idx_appr_one_pending_per_run ON approval_requests(task_id,
run_id) WHERE state='pending'` (índice parcial — SQLite suporta desde 3.8.0; o Python 3.11/3.13
dos labs traz SQLite bem acima disso). Uma segunda tentativa de abrir pendência no mesmo run
falha por `IntegrityError`, e o chamador trata como "já existe pedido para este run" em vez de
criar uma segunda fila humana.

### 2.2 Payload imutável

`payload_json` guarda a operação exata, e **é imutável após criação** (sem UPDATE; uma
mudança exige nova `request_id`):

```
{
  "op": "write_file" | "patch" | "multi_patch",
  "targets": [
    { "path_input":   "<o que o agente pediu>",
      "path_real":    "<os.path.realpath>",
      "is_symlink":   true|false,
      "symlink_to":   "<destino ou null>",
      "pre_sha256":   "<sha256 do conteúdo atual, ou null se não existe>",
      "pre_size":     <int ou null>,
      "post_sha256":  "<sha256 do conteúdo proposto>",
      "post_size":    <int>,
      "post_blob":    "<conteúdo final proposto, ver P-6>",
      "diff_unified": "<diff unificado, truncado em N KiB com marca explícita>" }
  ],
  "reasons": ["AGENTS.md", ...]   // rótulos de _protected_instruction_reason
}
```

Regras normativas:

**P-1.** Tanto `path_input` quanto `path_real` são gravados. A guarda atual já casa nos dois
(`file_tools_write_guards.py:209-213, 235`) — o contrato preserva essa dupla checagem e a
carrega para a revalidação (§4).

**P-2.** `pre_sha256` é da **preimagem**: o conteúdo no disco no instante da criação. `null`
significa "arquivo não existia" e é um valor distinto de qualquer hash.

**P-3.** `post_sha256` é do conteúdo final proposto, já aplicado o patch em memória. Para
`patch`, o contrato exige materializar o resultado — aprovar `old_string→new_string` sem o
resultado não é aprovar o conteúdo.

**P-4.** O diff mostrado ao humano (§5) é derivado **deste** payload, nunca regenerado por
LLM na hora de exibir nem na hora de escrever.

**P-5.** `request_hash = sha256(payload_json canônico, separadores fixos, chaves ordenadas)`
é gravado junto e é o que a UI exibe/ecoa. Uma decisão referencia `(request_id, request_hash)`.

**P-6. `post_blob` é obrigatório e é o que se escreve.** O conteúdo final vive no payload,
não na memória do processo — é o que permite que a escrita aconteça sem nenhuma chamada de
modelo (§4.0 R-3) e o que torna `post_sha256` verificável contra bytes reais, não contra uma
promessa. Conteúdo acima do teto configurado não vira pendência silenciosa: a guarda recusa a
operação com mensagem explícita (fail-closed), e o teto é decisão de implementação registrada
na etapa 1 do plano — nunca um truncamento que aprovaria conteúdo diferente do exibido.

### 2.3 Escopo da autorização

Uma decisão aprovada autoriza **exatamente**: escrever `post_blob` (cujo sha256 é
`post_sha256`) em `path_real`, desde que o conteúdo atual ainda tenha `pre_sha256` e o vínculo
de symlink ainda seja o registrado. Nada mais: nem outro arquivo, nem o mesmo arquivo com
outro conteúdo, nem uma segunda escrita. Um patch multi-arquivo é all-or-nothing, como já é
hoje (`file_tools_write_guards.py:329-331`).

## 3. Estados, transições e migração

### 3.1 Por que não reusar `blocked` nem `scheduled`

Medido:
- `block_task` (`kanban_db.py:3119-3181`) conta recorrência e, em
  `BLOCK_RECURRENCE_LIMIT = 2` (`kanban_db.py:111`), **roteia para `triage`**
  (`_route_block`, `kanban_db.py:3208`). Uma espera humana repetida viraria falha/triage —
  exatamente o que o H1 proibiu.
- `block_task` também encerra o run com `outcome="blocked"`, o que contamina histórico de
  tentativa com falha que não houve — e, crucialmente para §4.0, **mata a continuidade do
  processo**: o worker que bloqueia termina.
- `scheduled` (`kanban_db.py:3817-3843`) é "esperando tempo, não humano" e não é despachável;
  reusá-lo mente sobre a natureza da espera e colide com a semântica do dispatcher.

Portanto: **estado próprio**, como o H1 decidiu.

### 3.2 Novo estado `waiting_approval`

**E-1.** `waiting_approval` entra em `VALID_STATUSES` (`kanban_db.py:103`) e **não** entra em
`VALID_INITIAL_STATUSES` (`kanban_db.py:104`) — nenhum card nasce esperando aprovação.

**E-2.** Coluna própria na UI: `BOARD_COLUMNS` (`plugins/kanban/dashboard/plugin_api.py:169`)
passa a `[triage, todo, scheduled, ready, running, waiting_approval, blocked, review, done]`.
O desktop já renderiza colunas desconhecidas a partir do backend
(`apps/desktop/src/plugins/kanban/types.ts:215`), então a coluna aparece sem mudança de
protocolo; só o ícone/tom precisa de entrada nova ao lado de `blocked` (`types.ts:223`).

**E-3.** Transição de entrada — `pause_for_approval(conn, task_id, *, request_id, expected_run_id)`:

```
running --[guarda protegida disparou, request criada]--> waiting_approval
SET status='waiting_approval', claim_lock=NULL, claim_expires=NULL,
    worker_pid=NULL, worker_started_at=NULL, last_heartbeat_at=NULL
GUARD: WHERE status='running' AND current_run_id = :expected_run_id
run: NÃO encerra o run (current_run_id permanece) — ver E-3.1
evento: 'approval_requested' {request_id, request_hash, targets:[path_real…]}
NÃO toca consecutive_failures, block_kind, block_recurrences.
```

Libera claim e slot (o dispatcher conta `status='running'`,
`kanban_db_dispatch.py:1835-1849`), então a espera humana **não ocupa vaga do orçamento**.

**E-3.1. O run continua aberto, e isso é deliberado.** O worker não morreu (§4.0): ele está
bloqueado numa chamada de ferramenta. Encerrar o run aqui criaria uma tentativa fantasma e,
pior, habilitaria `reap_terminal_workers` (`kanban_db_dispatch.py:497-553`), que mata processos
de runs encerrados após `TERMINAL_WORKER_REAP_GRACE_SECONDS = 120` — ou seja, o próprio worker
que espera a decisão seria morto em 2 minutos. O run fica aberto e a tentativa é fechada por
quem realmente termina (retomada, deny, cancelamento, crash).

**E-4.** Transições de saída, todas com CAS sobre `(status='waiting_approval', request_id)`:

| Gatilho | Novo status | Evento | Observação |
|---|---|---|---|
| decisão `approve` | permanece `waiting_approval` até a escrita; depois `running` | `approval_granted` | **não** vai a `ready`; nenhum respawn de LLM — §4.0 |
| decisão `deny` | `blocked` (kind `needs_input`) | `approval_denied` | recorrência conta aqui, de propósito: deny repetido é sinal humano |
| cancelamento humano | `blocked` (kind `needs_input`) | `approval_cancelled` | |
| obsolescência (preimagem mudou) | `blocked` (kind `needs_input`) | `approval_obsolete` | detectada na revalidação (§4) ou por varredura |
| worker morreu esperando | `blocked` (kind `needs_input`) | `approval_orphaned` | §4.4 R-7; a request vira `cancelled`, nunca fica pendente sem dono |
| card arquivado/concluído por humano | segue o verbo humano | `approval_superseded` | a request é fechada, não some |

**E-5.** `waiting_approval` **não** é promovido por `recompute_ready`
(`kanban_db.py:2127-2147`). Há defesa em duas camadas no código atual — o `SELECT` varre
só `('todo','blocked')` **e** o `UPDATE` do ramo `todo` carrega `AND status = 'todo'`
(`kanban_db.py:2176-2180`). A implementação **preserva as duas**: ampliar só uma delas não
promove, o que torna um erro parcial silencioso. Exigir teste comportamental (não de
leitura de fonte) que prove que uma task em `waiting_approval` continua parada após a
varredura — adicioná-la ali criaria o respawn-loop que o H1 proibiu.

**E-6.** `waiting_approval` não é reclamável: `claim_task` só faz CAS de `ready`
(`kanban_db.py:2262+`), `claim_review_task` só de `review`. Nenhum caminho novo de claim.

**E-7.** O dispatcher não trata `waiting_approval` como stale nem como crash. Medido: todas as
varreduras de reciclagem filtram `status='running'` (`detect_stale_running`,
`kanban_db_dispatch.py:769`; `reconcile_orphaned_running`, `:1136-1138`; expiração de claim,
`kanban_db.py:2470-2477`), e a pausa zera `worker_pid`/`claim_lock`/`last_heartbeat_at`. A task
sai naturalmente das três. Exigir teste que prove isso, porque essas varreduras são as que
poderiam converter demora humana em falha. A contrapartida — o worker que espera precisa
continuar visível como vivo para §4.4 R-7 — é resolvida pelo `created_by_pid` da própria
request, não por um `worker_pid` em `tasks`.

**E-8. Saída genérica é recusada no ponto de código, não por convenção.** Hoje
`_drag_to` (`plugin_api.py:536-545`) só trata `blocked`/`scheduled`/`review` e cai em
`_set_status_direct` (`:703-731`), cujo `UPDATE tasks SET status=?` **não tem guarda de status
de origem** — depois de E-1, arrastar um card de `waiting_approval` para `ready` sairia da
espera sem consumir grant e sem o controle humano. Exigência normativa:

- `_set_status_direct` ganha `AND status != 'waiting_approval'` no `WHERE` do UPDATE (guarda de
  ORIGEM, camada 1) **e** uma recusa explícita antes do txn que devolve mensagem acionável
  (camada 2). Duas camadas pelo mesmo motivo de E-5: ampliar/errar uma não abre o portão.
- `_apply_status` (`:568-576`) recusa qualquer verbo quando o status atual é
  `waiting_approval`, exatamente como já recusa o destino `running` com `_RUNNING_DIRECT_MSG`.
  Vale para `PATCH /tasks/{id}` e para `POST /tasks/bulk`, que compartilham o mesmo dispatch.
- `waiting_approval` **não** entra em `_STATUS_HANDLERS`: não é destino atingível por verbo
  genérico, nem origem abandonável por ele. Único caminho de saída: o endpoint de decisão
  (§5 U-7), que exige `(request_id, request_hash)`.
- `unblock_task` (`kanban_db.py:3509-3550`) já só aceita `status IN ('blocked','scheduled')` —
  medido — então não é porta; a exigência é **não** adicioná-lo à lista.

### 3.3 Timeout de processo ≠ validade da solicitação

**T-1.** O timeout de aprovação em memória (`approvals.timeout`, usado por `_poll_event`)
continua governando **apenas** a espera síncrona de superfícies vivas.
**T-2.** A `approval_request` **não expira por tempo**. Ela termina só por decisão humana,
cancelamento, obsolescência por mudança de preimagem, ou morte do worker que a criou
(§4.4 R-7). Sem prazo, sem varredura que "limpa por antiguidade".
**T-3.** O worker que espera **não** pode ser morto por tempo de execução: `enforce_max_runtime`
e `detect_stale_running` não o alcançam (E-7), e `max_runtime_seconds` da task, se configurado,
deve descontar o tempo em `waiting_approval` — caso contrário a demora do humano vira timeout
do agente, que é a falha que este contrato existe para evitar. Critério C-30.

### 3.4 Migração aditiva (nenhum DROP, nenhum backfill destrutivo)

Segue o padrão já usado: colunas/tabelas adicionais em
`hermes_cli/kanban_db_connect.py` (`_migrate_add_optional_columns`, listas
`_LATER_TASK_COLUMNS` etc.), idempotente, `IF NOT EXISTS` para índices.

O DDL abaixo é **a mesma lista de §2.1**, sem campo a mais nem a menos:

```sql
CREATE TABLE IF NOT EXISTS approval_requests (
  request_id            TEXT PRIMARY KEY,
  task_id               TEXT NOT NULL,
  run_id                INTEGER NOT NULL,
  claim_lock            TEXT NOT NULL,
  profile_home          TEXT NOT NULL,
  session_key           TEXT NOT NULL,
  workspace_path        TEXT NOT NULL,
  created_by_pid        INTEGER NOT NULL,
  created_by_started_at TEXT NOT NULL,
  origin_session        TEXT,              -- único nullable (§2.1)
  payload_json          TEXT NOT NULL,     -- imutável (P-6 inclui post_blob)
  request_hash          TEXT NOT NULL,     -- sha256 do payload canônico
  state                 TEXT NOT NULL,     -- pending|granted|denied|cancelled|obsolete|consumed
  decided_at            INTEGER,
  decided_by            TEXT,              -- superfície + identidade humana, NUNCA um perfil de agente
  decision_surface      TEXT,              -- desktop|tui|cli|gateway
  consumed_at           INTEGER,           -- uso único: NOT NULL após o consumo
  created_at            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appr_task_state ON approval_requests(task_id, state);
CREATE INDEX IF NOT EXISTS idx_appr_state ON approval_requests(state);
-- U-3: no máximo UMA pendência por run (§2.1)
CREATE UNIQUE INDEX IF NOT EXISTS idx_appr_one_pending_per_run
  ON approval_requests(task_id, run_id) WHERE state = 'pending';
```

Sem coluna `board`: a tabela vive dentro do `kanban.db` do board (§2.1).

**M-1.** Boards antigos (sem a tabela) continuam abrindo: a migração cria e segue.
**M-2.** Nenhuma linha de `tasks` é reescrita pela migração.
**M-3.** Um board antigo não tem card em `waiting_approval`, logo não há estado a converter.
**M-4.** Downgrade: uma versão anterior do código ignora a tabela; um card parado em
`waiting_approval` ficaria invisível ao dispatcher antigo (não despachado, não perdido). Isso
é degradação aceitável e deve ser declarada na nota de rollout — não é reversível
automaticamente.

## 4. Retomada determinística de uso único

### 4.0 Quem escreve — o ator nativo, sem LLM (bloqueador R1 #1)

Este é o ponto que v1 não fechava. A regra:

**R-0. O ator que aplica o payload é o worker que o criou, ainda vivo, dentro da mesma
chamada de ferramenta.** A guarda protegida (`_check_protected_instruction_write`,
`file_tools_write_guards.py:329-339`) é chamada de dentro de `write_file_tool` /
`patch_file_tool` (`tools/file_tools.py:828-841`), na thread da ferramenta. Quando não há canal
humano, ela hoje retorna `_NO_HUMAN` e a escrita falha. O contrato substitui esse retorno, **no
contexto de worker Kanban** (`agent.delegation_context.owned_kanban_task()` não-vazio), por:

```
1. materializa o payload (§2.2, inclui post_blob)
2. cria a approval_request (state='pending')   -- uma por run (§2.1 U-3)
3. pause_for_approval(...)                      -- libera claim/slot, card -> waiting_approval
4. BLOQUEIA nesta thread, em polling do estado da request no banco
   (o mesmo formato de espera de _await_gateway_decision, com backoff)
5. ao ver 'granted': consome + revalida + escreve (§4.2), tudo aqui
6. retorna à ferramenta o resultado real da escrita
```

O processo do worker **não termina** na pausa e **não é respawnado**. Portanto:

- não existe "quem materializa `post_sha256` sem o loop do agente": é o mesmo processo, na
  mesma pilha, que já tinha o conteúdo — e o conteúdo também está no payload (P-6), então a
  escrita não depende sequer da memória viva;
- **nenhuma chamada de modelo acontece entre a decisão e a escrita.** O passo 5 é código Python
  determinístico. `claim_task` + `Popen` (`kanban_db_dispatch.py:2841-2848`), que é o caminho
  que spawna um worker LLM novo com `stdin=DEVNULL`, **não é acionado**, porque `approve` não
  leva o card a `ready` (E-4);
- o "sinal de saída do processo vivo após a pausa" que R1 pedia é: **não há saída**. O worker
  continua no passo 4 e sai quando a operação termina — pela ferramenta retornando (grant),
  pela guarda retornando erro (deny/obsolete/cancel), ou por morte do processo, que o §4.4 R-7
  trata como órfã. A liberação de slot e claim, que era a razão de querer matar o worker, já
  foi obtida em E-3 sem matá-lo.

**R-0.1. Custo declarado, não escondido.** O worker ocupa um processo do SO enquanto espera
(sem vaga do orçamento do dispatcher, sem claim, sem chamada de modelo — o loop do agente está
parado dentro da ferramenta, então não há consumo de token). É uma troca deliberada: um
processo parado em `poll`+`sleep` custa memória residente, e é o preço de não regenerar a
operação por LLM. Uma espera de dias é aceitável para o processo; se o host reiniciar, a request
vira órfã (R-7) e o humano vê `blocked`/`needs_input` em vez de uma escrita fantasma.

**R-0.2. Fora do contexto de worker Kanban, nada muda.** CLI e gateway continuam pelo caminho
síncrono existente (`_await_gateway_decision` / callback). O contrato só adiciona um ramo quando
`owned_kanban_task()` é não-vazio, o helper que o próprio repositório já define como "identidade
de worker" (`agent/delegation_context.py:76-84`) — não o mero `HERMES_KANBAN_TASK`, que children
e cron herdam.

### 4.1 Consumo atômico

A retomada consome a decisão com CAS numa única transação:

```sql
UPDATE approval_requests
   SET state='consumed', consumed_at=:now
 WHERE request_id=:rid AND state='granted' AND consumed_at IS NULL
```

`rowcount != 1` → não autoriza. Duplo clique, replay e dois workers concorrentes perdem
todos menos um; o perdedor não escreve e reporta "decisão já consumida".

### 4.2 Consumo, revalidação e escrita na MESMA região crítica (bloqueador R1 #4)

**R-2.** A ordem é consumir → revalidar → escrever, **tudo sob o mesmo lock**, sem janela
entre a checagem e a escrita:

1. adquire o lock do arquivo (ver R-2.1);
2. CAS de consumo (§4.1) — dentro do lock, não antes;
3. `os.path.realpath(path_input) == path_real` (symlink não foi repontado);
4. estado de symlink igual ao registrado;
5. `sha256(conteúdo atual) == pre_sha256` (ou ambos "não existe");
6. escreve `post_blob`; confere `sha256(bytes escritos) == post_sha256`;
7. libera o lock.

Qualquer divergência em 3–5 → **não escreve**, marca a request `obsolete`, card vai a `blocked`
(`needs_input`) com o motivo. Isso cobre "preimagem alterada". Divergência em 6 é falha de I/O
e recebe o mesmo tratamento fail-closed.

**R-2.1. O lock tem de ser cross-process, e o atual não é.** MEDIDO: `file_state.lock_path`
(`tools/file_state.py:78-95`, exposto em `:240-241`) é um `threading.Lock` em um registro
de processo (`FileStateRegistry`, `:66-75`) — serializa threads do MESMO processo e **não vê**
outro processo. O worker que escreve e a superfície humana são processos distintos, e dois
workers de tasks diferentes também são; um lock intra-processo ali seria TOCTOU com aparência
de proteção. Exigência: a região crítica usa **lock de arquivo do SO**, no padrão já presente
no repositório — `fcntl.flock(LOCK_EX)` em POSIX e `portalocker` fora dele, exatamente como
`tools/mcp_tool_loop.py:23-60` faz para a descoberta MCP (inclusive manter o descritor aberto
enquanto se segura o lock, que é a pegadinha documentada lá). `lock_path` continua sendo
tomado **por dentro** para a serialização intra-processo que ele já garante; não é substituído,
é insuficiente sozinho. Critério C-31 mede isso com dois processos reais.

**R-3. Sem regeneração por LLM.** O conteúdo escrito é `payload.targets[].post_blob`, lido da
própria request. O worker retomado não recalcula o patch, não reconsulta o modelo para produzir
o conteúdo, e não reabre a decisão. Um worker que precise de conteúdo diferente cria **nova**
request. Corolário de §4.0: como a escrita acontece no mesmo processo que ainda está dentro da
chamada de ferramenta, não existe nem a oportunidade de uma nova rodada de modelo entre a
decisão e a escrita.

**R-4. Um gesto humano.** Uma request aprovada não gera segundo prompt para a mesma
operação: ao retomar, a guarda protegida encontra a request `granted` correspondente
(mesmo `request_hash`) e consome, em vez de abrir novo pedido. Se o hash não bate, é outra
operação e um novo pedido é legítimo.

### 4.3 Crash e replay

**R-5. Crash entre consumo e escrita.** A decisão está `consumed` e o arquivo não mudou: a
operação **não** é reexecutada automaticamente. Fail-closed deliberado — perder uma escrita
autorizada é preferível a escrever duas vezes ou escrever sem revalidação.

**R-5.1. E o card NÃO volta a `ready` nesse instante (bloqueador R1 #4).** No momento do crash
o card está em `waiting_approval` (E-4: `approve` não o move até a escrita concluir), e
`waiting_approval` está fora de `detect_stale_running` / `reconcile_orphaned_running` / expiração
de claim, que só varrem `running` (E-7, medido). Logo nenhuma varredura o promove nem respawna
um worker que regeneraria a operação. Quem o tira de lá é a varredura de órfãs (R-7), que o leva
a `blocked`/`needs_input` com a evidência — nunca a `ready`. O card só entra em `running` depois
da escrita concluída, quando o worker retoma seu curso normal, e aí o regime de stale volta a
valer legitimamente.

**R-6. Escrita fora da janela.** Nenhuma escrita em arquivo protegido ocorre sem um consumo
`granted→consumed` na mesma região crítica. A guarda atual
(`_check_protected_instruction_write`, `file_tools_write_guards.py:329-339`) continua sendo
o único portão; ela passa a consultar/criar a request em vez de apenas falhar fechado.

### 4.4 Órfãs

**R-7. Request cuja criadora morreu.** Uma request `pending` ou `granted` cujo
`(created_by_pid, created_by_started_at)` não está mais vivo — mesmo predicado de
`_worker_alive` (`kanban_db_dispatch.py:375`), que já compara PID **e** fingerprint de início
justamente contra reciclagem de PID — é **órfã**: ninguém vai consumi-la. A varredura do
dispatcher (a mesma passada que já roda `reap_terminal_workers`) marca a request `cancelled`
com motivo `worker_gone` e leva o card de `waiting_approval` a `blocked`/`needs_input`, evento
`approval_orphaned`. Não reexecuta, não aprova, não apaga histórico. Sem esta regra, T-2 (a
request não expira) viraria uma pendência eterna que o humano poderia aprovar para ninguém.

**R-7.1.** A janela de graça antes de declarar órfã é a mesma já usada para não matar um worker
que ainda está se finalizando (`TERMINAL_WORKER_REAP_GRACE_SECONDS = 120`,
`kanban_db_dispatch.py:51`), para não transformar uma pausa recém-criada em órfã por corrida
de escrita da linha.

## 5. UI, contador e aviso

**U-1. Persistência.** A pendência vive no banco (§3.4), não em socket. Fechar e reabrir a
UI relista de `approval_requests WHERE state='pending'`. Nenhuma memória de processo é
fonte da lista.

**U-2. Card.** O card em `waiting_approval` mostra: alvo(s) (`path_real`), motivo
(rótulo de `_protected_instruction_reason`), e o diff do payload (§2.2, P-4). Controle
humano `Approve this change` desmarcado por padrão, mais `Deny` e `Cancel`.

**U-3. Contador.** Contagem no topo do board = `COUNT(*) FROM approval_requests WHERE
state='pending'`, servida junto de `GET /board` (`plugin_api.py:321`), não derivada do número
de cards (um card pode ter mais de uma request ao longo do tempo; só uma `pending` por run, e
agora isso é o índice único de §2.1/§3.4).

**U-4. Aviso na origem.** Entregue pelo caminho nativo já existente de notificação Kanban
(`kanban_notify_subs` + `gateway/kanban_watchers.py:60-121` /
`tui_gateway/session_notifications.py`), reusando o cursor de eventos. O evento
`approval_requested` entra em `TERMINAL_KINDS`
(`gateway/kanban_watchers_notifier.py:36`) e no espelho de
`tui_gateway/session_notifications.py:134` — as duas listas, ou o aviso sai numa superfície e
some na outra.

**U-5. Entrega comprovada, e falha de aviso não autoriza nada.** O aviso só conta como
entregue quando o adapter confirma (`record_notify_ping` / `advance_notify_cursor` — o cursor
só avança em entrega, com `rewind_notify_cursor` no fracasso, `kanban_db_notify.py:392-421`).
Falha de entrega: a request permanece `pending`, o card permanece `waiting_approval`, a escrita
permanece bloqueada. Aviso não é autorização em nenhuma direção.

**U-6. Estados Datadog (SDD-MUST-615).** A coluna e o card exibem explicitamente
loading / empty / error / forbidden. Texto de UI em inglês (regra 12-G); comentário e
documento em pt-BR.

**U-7. Nenhuma porta genérica — endpoint próprio.** O controle de aprovação não é um booleano
gravável por `PATCH /tasks/{id}`; é um endpoint próprio
(`POST /api/plugins/kanban/approvals/{request_id}/decide`) que:
- exige `(request_id, request_hash)` no corpo e recusa hash divergente (a preimagem mudou
  desde o que o humano viu);
- só existe na superfície humana autenticada do dashboard, com a mesma checagem de auth das
  demais rotas do plugin;
- grava `decided_by` (identidade humana) e `decision_surface`, nunca um perfil de agente;
- é o **único** caminho que tira um card de `waiting_approval` (E-8).

## 6. Plano de implementação, revisão e rollout

Etapas pequenas, sequenciais, no mesmo worktree. Cada uma termina verde e revisável
sozinha. Os tempos são **estimativas do autor, não medidas e não prazo prometido**.

| # | Escopo | Arquivos/interfaces | Estimativa |
|---|---|---|---|
| 1 | Journal + migração aditiva | `kanban_db_connect.py` (DDL §3.4 + índice único parcial), `kanban_db.py` (CRUD de `approval_requests`, `VALID_STATUSES`), teto de `post_blob` | 2–3 h |
| 2 | Estado e transições | `kanban_db.py` (`pause_for_approval` §3.2 E-3, saídas E-4), guardas de `recompute_ready`/claim/stale (E-5..E-7) | 3–4 h |
| 3 | Guarda protegida integrada + espera no processo | `tools/file_tools_write_guards.py` (ramo de worker Kanban §4.0, polling), `tools/file_tools.py` (materializar `post_blob`/`post_sha256`) | 5–7 h |
| 4 | Retomada, uso único e região crítica | consumo CAS + revalidação + escrita sob `flock` (§4.2, R-2.1), fail-closed em crash (R-5), varredura de órfãs (R-7) no tick do dispatcher | 4–5 h |
| 5 | Superfície | `plugins/kanban/dashboard/plugin_api.py` (coluna E-2, contador U-3, endpoint U-7, recusas E-8 em `_apply_status`/`_set_status_direct`), `apps/desktop/src/plugins/kanban/{board,drawer,types,api}.ts*` | 5–7 h |
| 6 | Aviso na origem | `gateway/kanban_watchers_notifier.py` (`TERMINAL_KINDS`), `tui_gateway/session_notifications.py` (espelho), recibo | 2–3 h |
| 7 | Prove + revisão + rollout | matriz §7 em Docker não-root; revisão CISO/QA independente; prova humana real na UI instalada; plano de drenagem sem matar worker | 4–6 h |

Total estimado 25–35 h, **não medido** (v1 dizia 22–32 h; a subida vem das etapas 3 e 4, que
ganharam a espera no processo e o lock cross-process). Etapas 1–2 e 5 podem correr em paralelo
depois que o journal estiver congelado; 3–4 não.

## 7. Matriz de critérios executáveis

Legenda de prova: `F` = fixture isolada (este contrato,
`fixtures/test_contrato_aprovacao.py`); `I` = teste de integração a escrever na
implementação; `H` = prova humana real na UI instalada (não substituível por fixture).

| # | Critério | Precondição verificável | Prova |
|---|---|---|---|
| C-01 | `block_task` libera claim/slot | `claim_lock`/`worker_pid` viram NULL | F (verde hoje) |
| C-02 | Repetir `block_task` do mesmo kind escala a `triage` | `BLOCK_RECURRENCE_LIMIT=2` | F (verde hoje — justifica o estado novo) |
| C-03 | `waiting_approval` é status válido | em `VALID_STATUSES` | F (RED hoje) |
| C-04 | `waiting_approval` não é status inicial | fora de `VALID_INITIAL_STATUSES` | F |
| C-05 | Pausa não conta falha nem recorrência | `consecutive_failures`/`block_recurrences` inalterados | I |
| C-06 | Pausa libera claim e não ocupa slot | `count_running_tasks` não inclui a task | F (precondição) + I |
| C-07 | `recompute_ready` não promove `waiting_approval` | varredura só `todo`/`blocked` | F (verde hoje) + I |
| C-08 | Stale/crash/max-runtime ignoram `waiting_approval` | sem `worker_pid`, sem `running` | F (precondição) + I |
| C-09 | Tabela `approval_requests` existe e é aditiva | board antigo abre e migra | F (RED hoje) + I |
| C-10 | Payload imutável | UPDATE em `payload_json` recusado | I |
| C-11 | `request_hash` casa payload canônico | sha256 estável, chaves ordenadas | F |
| C-12 | Consumo é uso único | segundo CAS `rowcount=0` | F + I |
| C-13 | Duplo clique não escreve duas vezes | uma escrita, uma request `consumed` | F + I |
| C-14 | Preimagem alterada não autoriza | `pre_sha256` divergente → `obsolete`, sem escrita | F + I |
| C-15 | Symlink repontado não autoriza | `realpath` divergente → sem escrita | F + I |
| C-16 | Deny não escreve | card `blocked`/`needs_input`, arquivo intacto | F (CAS recusa `denied`) + I |
| C-17 | Origem/perfil errado não autoriza | `profile_home`/`session_key` divergentes recusam | I |
| C-18 | Demora longa preserva a pendência | relógio controlado; request segue `pending` | I |
| C-19 | Reabrir a UI relista a pendência | lista vem do banco, não de socket | I + H |
| C-20 | Crash na retomada não escreve nem reexecuta | `consumed` sem escrita → `blocked` | I |
| C-21 | Falha de aviso não libera escrita | cursor rebobinado, request `pending` | I |
| C-22 | Aviso só conta com recibo | `advance_notify_cursor` só em entrega | I |
| C-23 | Comentário no card não aprova | `add_comment` não muda `state` | F (verde) |
| C-24 | `PATCH /tasks` genérico não aprova | `_STATUS_HANDLERS` sem verbo de aprovação | **F (verde, medido no lab com `fastapi`; mutante 3 morto)** |
| C-25 | Nenhuma ferramenta do worker aprova | lista de `kanban_*` sem verbo de decisão | F (verde) |
| C-26 | Portão protegido não honra yolo/allowlist | yolo ligado ainda exige humano; gate comum libera | F (verde, mutante morto) |
| C-27 | Sem canal humano continua falhando fechado | `_NO_HUMAN` preservado fora de contexto Kanban | F (verde) — RED original |
| C-28 | Coluna/contador/diff na UI instalada | exercício ponta a ponta pelo operador | H |
| C-29 | Aprovação humana real autoriza a escrita exata | H1 decide na UI; agente não clica | H |
| **C-30** | Espera humana não conta para `max_runtime_seconds` | tempo em `waiting_approval` descontado (T-3) | I |
| **C-31** | Região crítica serializa entre PROCESSOS | dois processos reais disputam; só um consome/escreve (R-2.1) | **F (verde, medido com 2 processos)** |
| **C-32** | Saída de `waiting_approval` por verbo genérico é recusada | `_set_status_direct`/`_apply_status`/bulk recusam a ORIGEM (E-8) | F (RED hoje: guarda de origem ainda não existe) + I |
| **C-33** | Uma pendência por run é constraint do banco | índice único parcial rejeita a segunda `pending` (§2.1) | F |
| **C-34** | Request órfã não fica pendente para sempre | worker morto → `cancelled`/`approval_orphaned`, card `blocked` (R-7) | I |
| **C-35** | `approval_requested` é notificável nas DUAS listas | `TERMINAL_KINDS` do gateway e espelho do TUI (U-4) | F (RED hoje) |

## 8. Limite do que as fixtures provam

As fixtures deste contrato rodam contra `kanban_db` real em banco temporário, com imports
reais, em Docker não-root. Prova de execução e controle negativo:
`prova-fixtures-contrato.md`.

Elas provam **precondições e guardas de fluxo**: que os estados/valores existem (ou ainda
não existem, RED estrito), que as portas genéricas não decidem, que o portão protegido
não cede a yolo (com controle positivo na mesma medição: o gate comum cede), que o CAS de
consumo é uso único, que a revalidação reprova preimagem e symlink alterados, e — novo em v2 —
que a serialização entre **processos** funciona com `flock` (C-31) e que `fastapi` está
presente no lab, então C-24 deixou de ser skip.

Elas **não** provam: entrega real de notificação, comportamento da UI instalada, ausência
de vulnerabilidade a processo hostil de mesmo UID (§1.3, Camada 2), nem que a implementação
futura respeita o contrato — isso é `I` e `H` na matriz. Também não provam o comportamento
temporal de uma espera longa real (C-18/C-30): fixture com relógio controlado é aproximação,
e a prova honesta é a etapa 7.

Os 79 controles verdes já existentes (`tests/tools/test_file_write_safety.py`,
`tests/hermes_cli/test_cli_approval_ui.py`) são controles preexistentes: **não** são GREEN
desta feature.

## 9. Pendências registradas para o orquestrador (não bloqueiam esta entrega)

1. **Decisão H1 sobre o risco residual §1.4** — recomendação (a), com o limite declarado.
   A implementação de §2–§6 não depende dela.
2. **Skills de processo ausentes (regra 12-E).** `atlas-publicacao` e `atlas-company-hats`
   não existem no perfil `arquiteto` (`skills_list` não as lista) nem versionadas em
   `ferramentas/skills/` deste worktree. O RACI desta entrega foi escrito à mão (§10). É
   frente própria: a ferramenta/regra precisa ir para o repositório.
3. **Downgrade (M-4)** não é automático; precisa de nota de rollout.
4. **Custo de processo parado (R-0.1)** — se a operação vier a esperar dias com frequência,
   vale medir memória residente de workers em espera antes de aumentar o paralelismo do board.
   Não é bloqueio da implementação; é medição da etapa 7.

## 10. RACI desta entrega

| Chapéu | Quem | Papel |
|---|---|---|
| PM/Rel | orquestrador | A do encaminhamento e do freeze |
| Arquiteto (autor) | arquiteto (este run) | R do contrato |
| CISO | revisor independente | R do parecer de segurança (§1, §4) — congela ou devolve |
| QA | revisor independente | R da matriz §7 (executável, negativos presentes) |
| db-analyst | revisor independente | R da migração §3.4 (aditiva, idempotente, índice parcial, downgrade) |
| CEO/H1 | H1 | A exclusivo da decisão humana de operações e do §1.4 |

Freeze respeitado neste run: nenhuma alteração em schema, banco vivo, instalação, config,
AGENTS/SOUL, nem reinício. Apenas `docs/evidencia/t_78aaa333/` foi escrito. O autor não
revisa a própria entrega.
