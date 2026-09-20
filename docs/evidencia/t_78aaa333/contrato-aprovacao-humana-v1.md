# Contrato executável — aprovação humana persistente para operações de worker Kanban

> **SUPERSEDIDO.** Esta é a v1, devolvida pelo revisor em R1 (comentário 1034 de t_069cfdac)
> com 4 bloqueadores de miolo. A versão em vigor é
> `contrato-aprovacao-humana-v2.md`, que fecha os quatro e registra em §0.1 o que mudou.
> Este arquivo é preservado como histórico auditável da revisão — não implementar a partir dele.

Versão: v1 (congelada nesta entrega). Autor: arquiteto (t_069cfdac).
Revisor exigido: CISO/QA independente, nunca o autor.
Norma: CYTRACKS-SDD v4.0-RC, 317 linhas, SHA-1 `8fc4a63af6144b81546f223e2dd5f23c038f5c4c`
(lido do objeto Git `origin/main:specops/CYTRACKS-SDD-v4.0-RC.md`, conferido neste run).

Rota efetiva do autor: `anthropic` / `claude-opus-5`, credencial OAuth em
`~/.hermes/profiles/arquiteto/auth.json` (campo `oauth` presente). Sem API paga por token,
sem wrapper ask-*/dev-*. Mesma família do revisor é permitida; não se alega diversidade.

## 0. O que este documento é e o que não é

É o contrato técnico que faltava para t_78aaa333 sair de bloqueio: define QUEM aprova,
O QUE está autorizado, COMO a espera persiste e COMO a operação retoma. Um leitor
implementa a partir daqui sem redefinir autoria nem conteúdo autorizado.

NÃO é: rollout, homologação de UI, aprovação de UX (já dada pelo H1), nem autorização
para escrever em AGENTS/SOUL. NÃO promove `rascunho-sincrono-nao-integrado.tar.gz`
(código incompleto, não executado).

Todas as referências de código abaixo foram lidas neste worktree
(`/Users/farantes/atlas/wt/kanban-aprovacao-interativa`, branch
`executor/kanban-aprovacao-interativa`, base `d7ea741ae04`). Nada foi alterado fora de
`docs/evidencia/t_78aaa333/`.

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
existente (`approval.respond` / callback CLI / `/approve`). Nenhuma outra porta cria decisão.

**A-2.** O registro persistido da decisão (§3) é **prova de auditoria, não fonte de
autoridade de execução**. O consumidor revalida o payload (§2, §4) antes de escrever; uma
linha de decisão sem preimagem coincidente não autoriza nada.

**A-3.** Portas explicitamente proibidas como aceite técnico, cada uma com o ponto de código
que precisa recusar:
- comentário/chat no card (`kanban_db.add_comment`, `hermes_cli/kanban_db.py:1762`);
- `PATCH /tasks/{id}` do dashboard e `POST /tasks/bulk`
  (`plugins/kanban/dashboard/plugin_api.py:551-571`, `_STATUS_HANDLERS`): a decisão de
  aprovação **não** entra como verbo de status genérico;
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
  (A-3); o consumo revalida preimagem (§4). Um agente que "acha" que foi aprovado não
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

Correlação obrigatória, todos os campos NOT NULL salvo indicação:
- `board` — slug do board (`_resolve_board`, `plugin_api.py:65`).
- `task_id`, `run_id` — run vigente (`tasks.current_run_id`); a solicitação pertence ao run.
- `claim_lock` — valor de `tasks.claim_lock` no instante da criação (`_claimer_id()`,
  `kanban_db.py:1086`). Prova que quem pediu detinha o claim.
- `profile_home` — caminho absoluto do `HERMES_HOME` do perfil (não o nome), porque o
  mesmo processo serve vários perfis e o nome é ambíguo.
- `session_key` — chave de aprovação do worker (`tools/approval_context.get_current_session_key`).
- `workspace_path` — `tasks.workspace_path` resolvido.
- `origin_session` — sessão/conversa de origem do card, para o aviso do §5. Nullable
  (cards criados sem origem persistida).
- `created_at`, `created_by_pid`, `created_by_started_at` (fingerprint do PID, mesmo par já
  usado por `_worker_alive`, `kanban_db_dispatch.py:375`).

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

### 2.3 Escopo da autorização

Uma decisão aprovada autoriza **exatamente**: escrever `post_sha256` em `path_real`, desde
que o conteúdo atual ainda tenha `pre_sha256` e o vínculo de symlink ainda seja o registrado.
Nada mais: nem outro arquivo, nem o mesmo arquivo com outro conteúdo, nem uma segunda
escrita. Um patch multi-arquivo é all-or-nothing, como já é hoje
(`file_tools_write_guards.py:329-331`).

## 3. Estados, transições e migração

### 3.1 Por que não reusar `blocked` nem `scheduled`

Medido:
- `block_task` (`kanban_db.py:3119-3181`) conta recorrência e, em
  `BLOCK_RECURRENCE_LIMIT = 2` (`kanban_db.py:111`), **roteia para `triage`**
  (`_route_block`, `kanban_db.py:3208`). Uma espera humana repetida viraria falha/triage —
  exatamente o que o H1 proibiu.
- `block_task` também encerra o run com `outcome="blocked"`, o que contamina histórico de
  tentativa com falha que não houve.
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
protocolo; só o ícone/tom precisa de entrada nova ao lado de `blocked`
(`types.ts:223`).

**E-3.** Transição de entrada — `pause_for_approval(conn, task_id, *, request_id, expected_run_id)`:

```
running --[guarda protegida disparou, request criada]--> waiting_approval
SET status='waiting_approval', claim_lock=NULL, claim_expires=NULL, worker_pid=NULL
GUARD: WHERE status='running' AND current_run_id = :expected_run_id
run: _end_or_synthesize_run(outcome='waiting_approval', status='waiting_approval')
evento: 'approval_requested' {request_id, request_hash, targets:[path_real…]}
NÃO toca consecutive_failures, block_kind, block_recurrences.
```

Libera claim e slot (o dispatcher conta `status='running'`,
`kanban_db_dispatch.py:1835-1849`), então a espera humana **não ocupa vaga nem LLM**.

**E-4.** Transições de saída, todas com CAS sobre `(status='waiting_approval', request_id)`:

| Gatilho | Novo status | Evento | Observação |
|---|---|---|---|
| decisão `approve` | `ready` | `approval_granted` | agenda exatamente uma retomada (§4) |
| decisão `deny` | `blocked` (kind `needs_input`) | `approval_denied` | recorrência conta aqui, de propósito: deny repetido é sinal humano |
| cancelamento humano | `blocked` (kind `needs_input`) | `approval_cancelled` | |
| obsolescência (preimagem mudou) | `blocked` (kind `needs_input`) | `approval_obsolete` | detectada na revalidação (§4) ou por varredura |
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

**E-7.** O dispatcher não trata `waiting_approval` como stale nem como crash: a task não tem
`worker_pid`, não está `running`, e portanto sai naturalmente de `detect_stale_running`,
`reconcile_orphaned_running` e `enforce_max_runtime`. Exigir teste que prove isso, porque
essas varreduras são as que poderiam converter demora humana em falha.

### 3.3 Timeout de processo ≠ validade da solicitação

**T-1.** O timeout de aprovação em memória (`approvals.timeout`, usado por `_poll_event`)
continua governando **apenas** a espera síncrona de superfícies vivas.
**T-2.** A `approval_request` **não expira por tempo**. Ela termina só por decisão humana,
cancelamento, ou obsolescência por mudança de preimagem. Sem prazo, sem varredura que
"limpa por antiguidade".

### 3.4 Migração aditiva (nenhum DROP, nenhum backfill destrutivo)

Segue o padrão já usado: colunas/tabelas adicionais em
`hermes_cli/kanban_db_connect.py` (`_migrate_add_optional_columns`, listas
`_LATER_TASK_COLUMNS` etc.), idempotente, `IF NOT EXISTS` para índices.

```sql
CREATE TABLE IF NOT EXISTS approval_requests (
  request_id      TEXT PRIMARY KEY,
  task_id         TEXT NOT NULL,
  run_id          INTEGER,
  claim_lock      TEXT,
  profile_home    TEXT NOT NULL,
  session_key     TEXT,
  workspace_path  TEXT,
  origin_session  TEXT,
  payload_json    TEXT NOT NULL,     -- imutável
  request_hash    TEXT NOT NULL,     -- sha256 do payload canônico
  state           TEXT NOT NULL,     -- pending|granted|denied|cancelled|obsolete|consumed
  decided_at      INTEGER,
  decided_by      TEXT,              -- superfície + identidade humana, NUNCA um perfil de agente
  decision_surface TEXT,             -- desktop|tui|cli|gateway
  consumed_at     INTEGER,           -- uso único: NOT NULL após o consumo
  created_at      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appr_task_state ON approval_requests(task_id, state);
CREATE INDEX IF NOT EXISTS idx_appr_state ON approval_requests(state);
```

**M-1.** Boards antigos (sem a tabela) continuam abrindo: a migração cria e segue.
**M-2.** Nenhuma linha de `tasks` é reescrita pela migração.
**M-3.** Um board antigo não tem card em `waiting_approval`, logo não há estado a converter.
**M-4.** Downgrade: uma versão anterior do código ignora a tabela; um card parado em
`waiting_approval` ficaria invisível ao dispatcher antigo (não despachado, não perdido). Isso
é degradação aceitável e deve ser declarada na nota de rollout — não é reversível
automaticamente.

## 4. Retomada determinística de uso único

**R-1. Consumo atômico.** A retomada consome a decisão com CAS numa única transação:

```sql
UPDATE approval_requests
   SET state='consumed', consumed_at=:now
 WHERE request_id=:rid AND state='granted' AND consumed_at IS NULL
```

`rowcount != 1` → não autoriza. Duplo clique, replay e dois workers concorrentes perdem
todos menos um; o perdedor não escreve e reporta "decisão já consumida".

**R-2. Revalidação antes da escrita**, na ordem, dentro do mesmo lock de path já existente
(`file_state.lock_path`, usado em `tools/file_tools.py:855+`):
1. `os.path.realpath(path_input) == path_real` (symlink não foi repontado);
2. estado de symlink igual ao registrado;
3. `sha256(conteúdo atual) == pre_sha256` (ou ambos "não existe");
4. o conteúdo a escrever tem `sha256 == post_sha256`.

Qualquer divergência → **não escreve**, marca a request `obsolete`, card vai a `blocked`
(`needs_input`) com o motivo. Isso cobre "preimagem alterada".

**R-3. Sem regeneração por LLM.** O conteúdo escrito é `payload.targets[].post_*`
materializado da própria request. O worker retomado não recalcula o patch, não reconsulta o
modelo para produzir o conteúdo, e não reabre a decisão. Um worker que precise de conteúdo
diferente cria **nova** request.

**R-4. Um gesto humano.** Uma request aprovada não gera segundo prompt para a mesma
operação: ao retomar, a guarda protegida encontra a request `granted` correspondente
(mesmo `request_hash`) e consome, em vez de abrir novo pedido. Se o hash não bate, é outra
operação e um novo pedido é legítimo.

**R-5. Crash na retomada.** Se o processo morre entre o consumo (R-1) e a escrita, a
decisão está `consumed` e o arquivo não mudou: a operação **não** é reexecutada
automaticamente. O card fica `blocked`/`needs_input` com a evidência. Essa é a escolha
deliberada (fail-closed): perder uma escrita autorizada é preferível a escrever duas vezes
ou escrever sem revalidação.

**R-6. Escrita fora da janela.** Nenhuma escrita em arquivo protegido ocorre sem um consumo
`granted→consumed` no mesmo processo e na mesma chamada. A guarda atual
(`_check_protected_instruction_write`, `file_tools_write_guards.py:329-339`) continua sendo
o único portão; ela passa a consultar a request antes de falhar fechado.

## 5. UI, contador e aviso

**U-1. Persistência.** A pendência vive no banco (§3.4), não em socket. Fechar e reabrir a
UI relista de `approval_requests WHERE state='pending'`. Nenhuma memória de processo é
fonte da lista.

**U-2. Card.** O card em `waiting_approval` mostra: alvo(s) (`path_real`), motivo
(rótulo de `_protected_instruction_reason`), e o diff do payload (§2.2, P-4). Controle
humano `Approve this change` desmarcado por padrão, mais `Deny` e `Cancel`.

**U-3. Contador.** Contagem no topo do board = `COUNT(*) FROM approval_requests WHERE
state='pending'` para o board corrente, servida junto de `GET /board`
(`plugin_api.py:321`), não derivada do número de cards (um card pode ter mais de uma request
ao longo do tempo; só uma `pending` por run).

**U-4. Aviso na origem.** Entregue pelo caminho nativo já existente de notificação Kanban
(`kanban_notify_subs` + `gateway/kanban_watchers.py:60-121` /
`tui_gateway/session_notifications.py`), reusando o cursor de eventos. O evento
`approval_requested` é um kind notificável.

**U-5. Entrega comprovada, e falha de aviso não autoriza nada.** O aviso só conta como
entregue quando o adapter confirma (`record_notify_ping` /
`advance_notify_cursor` — o cursor só avança em entrega, com `rewind_notify_cursor` no
fracasso, `kanban_db_notify.py:392-421`). Falha de entrega: a request permanece `pending`,
o card permanece `waiting_approval`, a escrita permanece bloqueada. Aviso não é
autorização em nenhuma direção.

**U-6. Estados Datadog (SDD-MUST-615).** A coluna e o card exibem explicitamente
loading / empty / error / forbidden. Texto de UI em inglês (regra 12-G); comentário e
documento em pt-BR.

**U-7. Nenhuma porta genérica.** O controle de aprovação não é um booleano gravável por
`PATCH /tasks/{id}`; é um endpoint próprio de decisão que exige `(request_id,
request_hash)` e só existe na superfície humana.

## 6. Plano de implementação, revisão e rollout

Etapas pequenas, sequenciais, no mesmo worktree. Cada uma termina verde e revisável
sozinha. Os tempos são **estimativas do autor, não medidas e não prazo prometido** — a
estimativa anterior de 16–32h do writer fica substituída por esta decomposição.

| # | Escopo | Arquivos/interfaces | Estimativa |
|---|---|---|---|
| 1 | Journal + migração aditiva | `kanban_db_connect.py` (DDL §3.4), `kanban_db.py` (CRUD de `approval_requests`, `VALID_STATUSES`) | 2–3 h |
| 2 | Estado e transições | `kanban_db.py` (`pause_for_approval`, saídas §3-E4), guardas de `recompute_ready`/claim/stale | 3–4 h |
| 3 | Guarda protegida integrada | `tools/file_tools_write_guards.py` (cria request + pausa quando em contexto Kanban; consome+revalida na retomada), `tools/file_tools.py` (materializar `post_sha256`) | 4–6 h |
| 4 | Retomada e uso único | dispatcher: retomar `ready` pós-`approval_granted`, consumo CAS, fail-closed em crash | 3–4 h |
| 5 | Superfície | `plugins/kanban/dashboard/plugin_api.py` (coluna, contador, endpoint de decisão), `apps/desktop/src/plugins/kanban/{board,drawer,types,api}.ts*` | 4–6 h |
| 6 | Aviso na origem | `gateway/kanban_watchers.py`, `tui_gateway/session_notifications.py` (kind notificável + recibo) | 2–3 h |
| 7 | Prove + revisão + rollout | matriz §7 em Docker não-root; revisão CISO/QA independente; prova humana real na UI instalada; plano de drenagem sem matar worker | 4–6 h |

Total estimado 22–32 h, **não medido**. Etapas 1–2 e 5 podem correr em paralelo depois que
o journal estiver congelado; 3–4 não.

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
| C-06 | Pausa libera claim e não ocupa slot | `count_running_tasks` não inclui a task | I |
| C-07 | `recompute_ready` não promove `waiting_approval` | varredura só `todo`/`blocked` | F (verde hoje) + I |
| C-08 | Stale/crash/max-runtime ignoram `waiting_approval` | sem `worker_pid`, sem `running` | I |
| C-09 | Tabela `approval_requests` existe e é aditiva | board antigo abre e migra | F (RED hoje) + I |
| C-10 | Payload imutável | UPDATE em `payload_json` recusado | I |
| C-11 | `request_hash` casa payload canônico | sha256 estável, chaves ordenadas | F |
| C-12 | Consumo é uso único | segundo CAS `rowcount=0` | I |
| C-13 | Duplo clique não escreve duas vezes | uma escrita, uma request `consumed` | I |
| C-14 | Preimagem alterada não autoriza | `pre_sha256` divergente → `obsolete`, sem escrita | I |
| C-15 | Symlink repontado não autoriza | `realpath` divergente → sem escrita | I |
| C-16 | Deny não escreve | card `blocked`/`needs_input`, arquivo intacto | I |
| C-17 | Origem/perfil errado não autoriza | `profile_home`/`session_key` divergentes recusam | I |
| C-18 | Demora longa preserva a pendência | relógio controlado; request segue `pending` | I |
| C-19 | Reabrir a UI relista a pendência | lista vem do banco, não de socket | I + H |
| C-20 | Crash na retomada não escreve nem reexecuta | `consumed` sem escrita → `blocked` | I |
| C-21 | Falha de aviso não libera escrita | cursor rebobinado, request `pending` | I |
| C-22 | Aviso só conta com recibo | `advance_notify_cursor` só em entrega | I |
| C-23 | Comentário no card não aprova | `add_comment` não muda `state` | F (verde) |
| C-24 | `PATCH /tasks` genérico não aprova | `_STATUS_HANDLERS` sem verbo de aprovação | F — **NÃO MEDIDO** (falta `fastapi` no lab; ver prova §3) |
| C-25 | Nenhuma ferramenta do worker aprova | lista de `kanban_*` sem verbo de decisão | F (verde) |
| C-26 | Portão protegido não honra yolo/allowlist | yolo ligado ainda exige humano; gate comum libera | F (verde, mutante morto) |
| C-27 | Sem canal humano continua falhando fechado | `_NO_HUMAN` preservado | F (verde) — RED original |
| C-28 | Coluna/contador/diff na UI instalada | exercício ponta a ponta pelo operador | H |
| C-29 | Aprovação humana real autoriza a escrita exata | H1 decide na UI; agente não clica | H |

## 8. Limite do que as fixtures provam

As fixtures deste contrato rodam contra `kanban_db` real em banco temporário, com imports
reais, em Docker não-root. Prova de execução e controle negativo:
`prova-fixtures-contrato.md` (11 verdes, 2 xfail estritos, 1 pulado visível; dois mutantes
mortos, um não medido).

Elas provam **precondições e guardas de fluxo**: que os estados/valores existem (ou ainda
não existem, RED estrito), que as portas genéricas não decidem, e que o portão protegido
não cede a yolo — este último com controle positivo na mesma medição (o gate comum cede).

Elas **não** provam: entrega real de notificação, comportamento da UI instalada, ausência
de vulnerabilidade a processo hostil de mesmo UID (§1.3, Camada 2), nem que a implementação
futura respeita o contrato — isso é `I` e `H` na matriz. E C-24 ficou **NÃO MEDIDO** por
falta de `fastapi` no lab disponível (detalhe na prova §3): é pendência da etapa 5.

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

## 10. RACI desta entrega

| Chapéu | Quem | Papel |
|---|---|---|
| PM/Rel | orquestrador | A do encaminhamento e do freeze |
| Arquiteto (autor) | arquiteto (este run) | R do contrato |
| CISO | revisor independente | R do parecer de segurança (§1, §4) — congela ou devolve |
| QA | revisor independente | R da matriz §7 (executável, negativos presentes) |
| db-analyst | revisor independente | R da migração §3.4 (aditiva, idempotente, downgrade) |
| CEO/H1 | H1 | A exclusivo da decisão humana de operações e do §1.4 |

Freeze respeitado neste run: nenhuma alteração em schema, banco vivo, instalação, config,
AGENTS/SOUL, nem reinício. Apenas `docs/evidencia/t_78aaa333/` foi escrito. O autor não
revisa a própria entrega.
