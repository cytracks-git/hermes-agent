# t_00542312 — Corpo de card gravado truncado pelo compressor de contexto

Executor (claude-opus-5 / anthropic). Risco ALTO: dado durável destruído em produção.

SDD v5 conferido do objeto git canônico:
`88ee6d80bc5aa356b56a96be6e534f551eef21d838bfd9e44d818d24a3c540db` — bate com o pin.

---

## 1. Inventário completo (DoD 1)

Varredura de `tasks.body` + `task_comments.body` no board atlas, **todos os status,
inclusive `archived`**. Critério de dano: marcador de compressão **TERMINAL** (o texto
acaba nele). Card que apenas CITA o marcador em prosa é falso-positivo.

```
### DANO REAL: 11 registros

tipo     id           ctx                     head  total  perdido
----------------------------------------------------------------------
task     t_836be40f   triage                   190   6547     6347
task     t_93ec4f92   done                     208   3055     2855
task     t_c505c2cc   ready                    176   5655     5455
comment  1633         t_c4fe5d87/executor      201   1237     1037
comment  1820         t_836be40f/executor      169   3196     2996
comment  1821         t_836be40f/executor      209   3933     3733
comment  1823         t_836be40f/executor      186   3075     2875
comment  1824         t_836be40f/executor      213   3090     2890
comment  1829         t_836be40f/executor      206   4034     3834
comment  1830         t_c505c2cc/executor      180   3067     2867
comment  1833         t_850dbb6d/executor      191   1296     1096
----------------------------------------------------------------------
TOTAL DE CHARS PERDIDOS: 35,985

### FALSO-POSITIVO (cita o marcador em prosa, corpo íntegro): 6
  task     t_00542312   len=2553      comment  972   t_5a6be335  len=3398
  task     t_7b02cb99   len=3040      comment  996   t_5a6be335  len=2667
                                      comment  1831  t_c505c2cc  len=4541
                                      comment  1864  t_a83c628d  len=3579
```

**O card dizia 14.657 chars em 3 bodies. O total real é 35.985 chars em 11 registros** —
os 12 comentários citados no corpo eram 8 danificados + 4 falso-positivos, e ninguém
tinha somado os comentários.

### Classe irmã, mesma causa: marcador NU `...[truncated]`

```
TOTAL classe irmã: 21 registros
  task    t_a83c628d triage    len=205   (runbook de publicação, perdido — vide c1864)
  task    t_6512cfd6 archived  len=217
  task    t_24a427ca archived  len=214
  + 18 comentários
```

Mesma imitação (#83714), marcador anterior. **A correção cobre as duas formas.**

---

## 2. Causa raiz (DoD 2)

### A aritmética descarta corte mecânico no writer

Se o compressor tivesse APLICADO o marcador, o head seria sempre
`total - omitted` = 200 (o `head_chars=200` de `_truncate_tool_call_args_json`):

```
registro                     head_real   total  omitted total-omitted  BATE?
tasks/t_93ec4f92                   208    3055     2855           200    NAO
tasks/t_836be40f                   190    6547     6347           200    NAO
tasks/t_c505c2cc                   176    5655     5455           200    NAO
```

Head real nunca é 200, e cai em **fronteira de palavra** (`...régua a cada fase.`,
`...há 3 dias, ent`). Cap de código daria sempre o mesmo número.

### O mecanismo

O marcador foi **IMITADO pelo modelo**, não aplicado pelo compressor. O próprio
`agent/context_compressor.py:1416-1420` documenta a classe (#83714, commit `262a6436fa`):

> *this text lands inside the model's OWN replayed tool call, so it must not read like
> something the model would write itself: the bare `"...[truncated]"` it replaced was
> imitated into new calls and **written to disk***

O compressor encurta a JANELA DE CONTEXTO — comportamento correto. O defeito é que
**não havia fronteira de admissão no lado do DADO DURÁVEL**: corpo de card e comentário
são conteúdo permanente, e aceitavam um recorte de contexto como se fosse texto original.

### Por que não corrigi dentro do compressor

Reescrever o marcador não resolve: qualquer texto que o modelo veja, ele pode imitar.
O comentário do #83714 já é a segunda tentativa nessa direção (marcador nu → delimitado),
e o dano continuou por 6 semanas depois dela. A correção que funciona é **recusar a
escrita na fronteira do dado durável**, onde a verificação é determinística.

### Trabalho órfão encontrado

`t_5a6be335` ("Card nasce TRUNCADO no Kanban", `done`, aprovado no run 523) entregou
`hermes_cli/kanban_task_body.py` em `~/atlas/wt/t_5a6be335-hermes` (commit `99de67b66a`).
**O pin em produção `~/.hermes/hermes-agent` (HEAD `587e13cbf9`) NÃO tem esse arquivo.**
Aprovado, nunca integrado, dano continuou — e o gate órfão cobria só 3 fronteiras,
deixando `add_comment` e `edit_task` abertos (12 dos 15 registros danificados eram
comentários). Esta entrega porta e ESTENDE para 6 fronteiras.

---

## 3. Correção aplicada

`hermes_cli/kanban_task_body.py` — recusa corpo/comentário que **termina** em marcador
de truncagem (as duas formas: delimitada e nua). Citar o marcador no meio da prosa
continua válido: este próprio relatório passa pela fronteira.

Ligada em **6 fronteiras de escrita**, todas medidas por `grep` em `INSERT INTO`/`UPDATE`:

| # | fronteira | arquivo |
|---|---|---|
| 1 | `create_task` | `hermes_cli/kanban_db.py` |
| 2 | `add_comment` | `hermes_cli/kanban_db.py` ← **novo** (12 dos 15 danos) |
| 3 | `edit_task` | `hermes_cli/kanban_db.py` ← **novo** |
| 4 | `specify_triage_task` | `hermes_cli/kanban_db.py` |
| 5 | `_validate_children_graph` | `hermes_cli/kanban_db_graph.py` |
| 6 | `_patch_title_body` (REST) | `plugins/kanban/dashboard/plugin_api.py` ← **novo** |

A 6ª era periferia apontada pelo revisor de `t_5a6be335` e estava aberta: o REST do
dashboard grava por `UPDATE` direto, sem passar por `edit_task`.

---

## 4. Provas (DoD 3) — container, uid não-root

Todas em `docker run -u "$(id -u):$(id -g)"` → `uid=502 gid=20`, **não root**.
Root ignora permissão e aprova por construção; por isso o uid vai colado.

### 4.1 Suíte focal: 20/20 verde

```
uid=502 gid=20(dialout) groups=20(dialout)
....................                                                     [100%]
20 passed in 2.37s
```

### 4.2 MUTANTE — sensor desligado, código real intacto

Módulo presente, fronteira neutralizada (`return  # MUTANTE`). Reproduz o
COMPORTAMENTO do pin em produção.

```
=== MUTANTE HONESTO: modulo presente, sensor NO-OP ===
E           Failed: DID NOT RAISE ValueError
9 failed, 11 passed in 3.39s
```

**Mutante morto**: os 9 negativos falham, e os **11 positivos continuam passando** — o
sensor não reprova todo mundo.

> Descartei um primeiro mutante (árvore no commit `587e13cbf9`) porque ele morria por
> `ModuleNotFoundError` no import, não por comportamento. Kill fraco não é prova.

### 4.3 CONTROLE NEGATIVO ponta-a-ponta — o que chega ao DISCO

Mesmo corpo, dois bancos SQLite reais (`docs/evidencia/t_00542312/prova_fronteira.py`).

**ANTES** (pin `587e13cbf9`, sem a fronteira):
```
=== ANTES — fronteira de admissao presente? False ===
[NEGATIVO] tentando gravar corpo truncado (394 chars, head 171 + marcador)
  ESCRITA PASSOU -> banco tem 394 chars
  termina em marcador? True
  RESULTADO: DADO DESTRUIDO NO DISCO (223 chars de marcador no lugar da spec)
[POSITIVO] gravando corpo longo integro (5967 chars)
  banco tem 5967 chars | integro (byte a byte)? True
[NEGATIVO-COMENTARIO] tentando gravar comentario truncado
  ESCRITA PASSOU -> task_comments agora tem 2 linhas (uma delas truncada)
```

**DEPOIS** (com a fronteira):
```
=== DEPOIS — fronteira de admissao presente? True ===
[NEGATIVO] tentando gravar corpo truncado (394 chars, head 171 + marcador)
  ESCRITA RECUSADA -> ValueError: body ends in a context-compression truncation marker...
  linhas em tasks apos a recusa: 0
  RESULTADO: NADA PERSISTIDO (o texto original segue vivo na origem)
[POSITIVO] gravando corpo longo integro (5967 chars)
  banco tem 5967 chars | integro (byte a byte)? True
  RESULTADO: PASSA INTEIRO
[NEGATIVO-COMENTARIO] tentando gravar comentario truncado
  ESCRITA RECUSADA -> ValueError; task_comments continua com 1 linha(s)
```

O ANTES reproduz o dano real do board (`t_c505c2cc`: head 176 + marcador de 223).

### 4.4 Regressão: ZERO

Mesma seleção (`-k kanban`), mesmo venv, no branch e no pin intocado:

```
BRANCH:    24 failed, 536 passed, 14 skipped  (230.71s)
BASELINE:  24 failed, 516 passed, 14 skipped  (259.08s)   ← pin 587e13cbf9
```

**As mesmas 24 falhas nos dois lados** (hooks, worktree unicode, write_guard — todas
preexistentes, nenhuma toca a fronteira de corpo). Delta = **+20 passed**, exatamente
os testes desta entrega. Nada quebrado.

---

## 5. Recuperação (DoD 4) — ESGOTADA, nada inventado

| fonte | resultado |
|---|---|
| 10 backups `kanban.db.bak-*` | todos de **2026-09-19**, anteriores ao dano (2026-09-22/23). Os 11 registros não existem neles |
| 294 dumps de sessão | âncora (40 chars finais do head) NÃO encontrada em nenhum |
| 222 logs de worker + anexos + WAL | NÃO encontrada (2 hits são os falso-positivos íntegros) |
| `task_events` payload `created` | só metadado (assignee/status/workspace), nunca o corpo |

**Nada foi reconstituído de memória ou inferência.** Inventar spec plausível apagaria o
rastro da perda — é pior que o buraco. Os 3 cards receberam comentário **NÃO MEDIDO**
nomeando exatamente o que se perdeu (c1979, c1980, c1981).

### Pendência honesta: não consegui editar os CORPOS

`hermes kanban edit` recusou: `delegate_task child contexts cannot mutate Kanban tasks`
(`HERMES_DELEGATED_CHILD_CONTEXT` setado nesta sessão). A guarda é legítima e **não a
contornei**. O texto pronto está em `/tmp/corpos-nao-medido/{t_93ec4f92,t_836be40f,t_c505c2cc}.md`;
quem tiver sessão não-delegada cola no corpo. Enquanto isso, **`t_c505c2cc` segue em
`ready` e reclamável com spec mutilada** — é o risco aberto desta entrega.

---

## 6. O que NÃO foi medido

- **Os 21 registros da classe irmã** (`...[truncated]`) não foram marcados um a um; só
  inventariados. A fronteira impede dano novo, mas o passado segue lá.
- **UI do dashboard**: a fronteira do REST foi provada por teste (`kanban_db.validate_task_body`),
  **não** exercitada pelo navegador — `fastapi` não está no venv do pin.
- **Os 8 comentários danificados** não receberam marcação individual (a API só permite
  adicionar comentário novo, não editar existente).

---

## 7. Erguer a régua (regra 7) — medido, NÃO executado

1. **O gate aprovado de `t_5a6be335` nunca chegou ao pin.** Não é caso isolado: o board
   tem 98 worktrees e `t_c505c2cc` (o card com spec destruída) é justamente sobre 1608
   commits que só existem em disco. Aprovar sem integrar é a classe que mantém o dano
   vivo depois do conserto. Custo de medir: baixo; risco de ignorar: alto.
2. **Os 21 registros da classe irmã** continuam truncados, incluindo o runbook de
   publicação de `t_a83c628d`. Recuperação já foi tentada e esgotada em c1864.
3. **`_compact_fallback_turn` (L1154) e `_latest_user_task_snapshot` (L4035)** ainda
   emitem o marcador nu no prompt. Não é mais dano durável (a fronteira barra), mas é a
   fonte que o modelo imita. Corrigir lá reduz a pressão sobre o sensor.

Nenhum card aberto (R<1): são defeitos reais sem ninguém travado agora. A decisão de
virar card é do orquestrador.
