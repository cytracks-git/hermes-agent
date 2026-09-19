# Rodada 3 do gate de evidencia — o que foi MEDIDO

Card `t_7e6fb387`. Esta rodada responde ao parecer do revisor sobre a rodada 2
(comentario 414), que reprovou o trabalho com tres falhas.

Tudo abaixo e saida real de execucao. Onde eu nao medi, esta escrito
NAO MEDIDO — nao ha adjetivo no lugar de numero.

---

## 0. O RED do revisor, reproduzido por mim

Nao tratei o parecer como verdade recebida. Rodei o harness DELE contra o meu
worktree no commit `3389414eb43`:

```
OK   W0 controle positivo (commit local, sem push)  esperado=RECUSOU  obtido=RECUSOU
OK   W2 forja update-ref refs/remotes (bloq.1 rodada1) esperado=RECUSOU  obtido=RECUSOU
OK   W7 SHA tipado inventado                        esperado=RECUSOU  obtido=RECUSOU
OK   W6 leitura pura scratch nao-git                esperado=ACEITOU  obtido=ACEITOU
FALHA W1 scratch + worktree externo, worker OMITE metadata  esperado=RECUSOU  obtido=ACEITOU
FALHA W3 worker aponta origin para bare repo que ele criou  esperado=RECUSOU  obtido=ACEITOU
FALHA W4 HEAD publicado + arquivos NAO commitados           esperado=RECUSOU  obtido=ACEITOU
OK   W5 HEAD publicado + summary mentiroso          esperado=ACEITOU  obtido=ACEITOU

conformes: 5/8
```

O parecer procede. As tres falhas sao reais e reproduzem.

Arquivo: `harness-revisor-rodada2.py`

---

## 1. Colateral no board de producao — defeito MEU, corrigido na causa

Antes do gate, um estrago que eu mesmo causei e que o orquestrador mediu: o
harness da rodada 2 criou **10 cards `assignee=worker` no board atlas real**.
Tres ocuparam o teto de 4 slots do dispatcher enquanto **23 cards de entrega**
esperavam em `ready`.

### Causa raiz (`causa-colateral-board.py`)

```
[A] harness standalone (so seta HERMES_HOME)
    HERMES_KANBAN_DB = /Users/farantes/.hermes/kanban/boards/atlas/kanban.db
    -> kanban_db_path() = /Users/farantes/.hermes/kanban/boards/atlas/kanban.db
    -> E O BANCO DE PRODUCAO? True

[B] pytest (conftest limpa os pins de kanban)
    -> kanban_db_path() = /var/folders/.../causa-t7e-752nzaru/.hermes/kanban.db
    -> E O BANCO DE PRODUCAO? False
```

E **precedencia**: `HERMES_KANBAN_DB`, injetado em todo worker, VENCE
`HERMES_HOME`. Setar so o segundo nao isola nada. A suite pytest nunca teve o
furo (`tests/conftest.py` ja limpa os pins); o furo era dos scripts avulsos.

### Conserto e prova

`isolar_board.py` limpa os 11 pins e **aborta** se o destino nao cair no HOME
descartavel. Prova com controle positivo embutido — um harness que nao roda
tambem "nao suja", entao exijo as duas coisas:

```
ANTES   total=108  assignee=worker=11
--- harness (rc=0) ---
  conformes: 5/8
DEPOIS  total=108  assignee=worker=11
PROVA: o harness rodou ate o fim e o board de PRODUCAO nao mudou.
       delta total=0  delta worker=0
```

### Sensor

`tests/hermes_cli/test_provas_isolam_o_board.py` (6 passed) congela a regra com
controle negativo (constroi o script vulneravel e exige reprova), controle
positivo e um teste que **mede a premissa** — se a precedencia mudar, o sensor
cai em vez de cobrar regra obsoleta.

Pegou o `harness-revisor-rodada2.py` na primeira execucao. Nao foi teatro.

**Residuo nao resolvido:** os 10 cards continuam no board. Arquivar e mutacao em
producao e a decisao e do dono. Os 3 em `ready` sao os que consomem slot.

---

## 2. FALHA 1 — omitir metadata era o atalho

A descoberta so via `workspace_path` + o que a metadata declarasse. Metadata e
escrita pelo worker: **calar fechava o card**.

Medido no board real (`medir-populacao-board.py`):

- **177 de 193** runs com metadata **calam** sobre o repo;
- **5 cards** reais guardam o trabalho em repo ANINHADO (`<workspace>/repo`),
  invisivel ao gate da rodada 2.

### Conserto

Duas fontes objetivas, nenhuma declarada pelo worker:

1. varredura por repos aninhados no workspace (profundidade 2 — medido: os 5
   cards reais usam profundidade 1);
2. `git worktree list --porcelain` filtrado pelo **task id** — o git responde, e
   o filtro preserva o RECORTE: worktree de outro card nao trava este.

Tambem corrigido o dedup: era por `git-common-dir`, passou a `git-dir`. Com
common-dir, dois worktrees do mesmo repo colidiam e o do card era **descartado
em silencio**.

---

## 3. FALHA 2 — o worker controla QUAL remoto

O gate prova que *um* remoto anunciou o commit, nao que seja o remoto certo.
Proibir remoto local nao serve: os proprios testes usam bare local legitimo e o
Atlas tem remoto `destino` separado.

Corrigida a **invisibilidade**. Medido (`substancia-w1-w3-w4.py`):

```
W3 — remoto forjado pelo worker: a forja ficou AUDITAVEL?
  status do card      : done
  URL gravada no evento: ['/var/folders/.../w3/remoto-de-mentira.git']
  aponta para a forja? : True
  origin REAL era      : /var/folders/.../w3/project-origin.git
```

O card fecha — **limitacao DECLARADA**, nao furo esquecido — mas a troca de
remoto virou linha auditavel. Antes nao havia registro nenhum.

---

## 4. FALHA 3 — a segunda perda do card

O card nasce de duas perdas; a de "53 arquivos em /tmp" nao estava coberta. O
caminho `worktree` ja preservava arvore suja; o `scratch` fazia `rmtree` sem
consultar nada.

```
W4 — worktree com arquivo NAO commitado: o trabalho SOBREVIVEU?
  status do card          : done
  arquivo ainda no disco? : True
```

Criterio e **durabilidade, nao tamanho**: arquivo ja anexado ao card nao segura
o diretorio, e workspace vazio continua sendo removido (22 dos 69 do board) —
preservar nao pode virar vazamento de disco. Evento
`workspace_preserved_unpublished`. **Nunca vira recusa**: o card proibe
transformar isso num quarto bloqueio.

---

## 5. Os QUATRO controles que o card exige

Saida real de `quatro-controles-do-card.py`. O controle 2 usa o **mesmo card**
do 1 de proposito: a unica variavel entre recusar e fechar e o `push`.

```
CONTROLE 1 — commit local, rama NAO empurrada        ESPERADO: RECUSAR
  RESULTADO: RECUSOU
    completion blocked: 1 commit(s) in .../c12/project branch trabalho-do-card
    (HEAD: 8656f9065da3...) are not announced by the remote. Run `git push` and retry.
  status do card: running

CONTROLE 2 — O MESMO card, apos `git push`           ESPERADO: FECHAR
  RESULTADO: complete_task=True  status=done

CONTROLE 3 — card de leitura pura, nenhum commit     ESPERADO: FECHAR
  RESULTADO: complete_task=True  status=done

CONTROLE 4 — metadata com SHA inventado              ESPERADO: RECUSAR
  RESULTADO: RECUSOU
    completion blocked: metadata claimed commit SHA(s) that no measured
    repository can resolve: deadbeef... Commit and push the work, or correct
    the SHA to one that exists.
  status do card: running

VEREDITO: 4/4 controles conformes
```

---

## 6. Mutante — o conserto matou a CLASSE?

Testes novos passando no codigo novo nao provam nada sozinhos. A pergunta e se o
codigo da rodada 2 **falha** nos mesmos testes (`mutante-rodada3.sh`):

```
MUTANTE: codigo da RODADA 2 (3389414eb43) contra os testes da RODADA 3
FAILED test_f1_repo_aninhado_no_workspace_sem_metadata_e_medido
FAILED test_f1_worktree_do_card_por_task_id_sem_metadata_e_medido
FAILED test_f2_url_do_remoto_que_aprovou_fica_gravada
FAILED test_f3_trabalho_nao_commitado_sobrevive_ao_fechamento
4 failed, 6 passed
```

Os **4 testes novos morrem** no codigo velho; os **6 controles passam nas duas
versoes** (nao sao verdes por construcao).

### O script de mutante ja destruiu trabalho uma vez

A primeira versao restaurava com `git checkout -- <alvos>`, que descarta
alteracoes **nao commitadas**. Rodei com o conserto ainda no working tree e ela
**apagou o conserto inteiro** — descobri porque a regressao seguinte acusou 19
falhas absurdas. Agora a restauracao e por copia fisica e o script **verifica**
que o marcador do conserto voltou:

```
marcador do conserto em kanban_db.py: 2 ocorrencia(s) (0 = RESTAURACAO FALHOU)
```

Licao registrada no proprio script: trabalho nao commitado nao sobrevive a
ferramenta que usa git para restaurar.

---

## 7. Regressao — zero regressao minha

Comparacao contra a baseline `3389414eb43` em worktree separado, mesmo
interpretador, mesmo comando:

```
baseline:       15 unicos | meu:       15 unicos

=== falhas SO no meu (regressao que eu causei) ===
(vazio)

=== falhas SO na baseline (que eu consertei) ===
(vazio)

baseline: 15 failed, 394 passed, 11 skipped
meu:      15 failed, 404 passed, 11 skipped
```

As 15 falhas sao **preexistentes** e identicas nas duas versoes; so aparecem no
run completo (`-k kanban`), nunca no subconjunto isolado — **69 passed** em ambos.
Sao contaminacao entre testes, anterior a este card. **+10 passes** sao os meus.

---

## 8. O que NAO foi resolvido — declarado, nao escondido

### W1: scratch nao-git + worktree externo + metadata omitida

```
W1 — status do card : done
  workspace      : .../w1/scratch-ws  (nao-git)
  trabalho em    : .../w1/project/.worktrees/ext-t_b7c91040  (nao empurrado)
```

**Continua fechando.** Nao existe ligacao objetiva entre o card e esse repo: o
workspace nao e git, a metadata cala, e o board atlas **nao tem
`default_workdir`** configurado para ancorar a busca (medido: a tabela de
metadata do board nao traz a chave).

As saidas que considerei e por que nao as tomei:

- varrer o disco atras de worktrees com o task id: custo indeterminado em todo
  `complete`, e resultado dependente de onde o worker resolveu criar o repo;
- exigir metadata obrigatoria: transformaria o gate no bloqueio burocratico que
  o card proibe, e 177 de 193 runs reais nao declaram nada.

**RETRATACAO (rodada 4).** Esta secao dizia, ate a rodada 3: *"A saida honesta
e configurar `default_workdir` no board — ai o worktree externo passa a ter
ancora objetiva."* **Isso esta ERRADO, e o revisor mediu** (`w1_default_workdir.py`):

```
  colunas de tasks com 'workdir': []
  _resolve_evidence_repos menciona default_workdir? False
  => _descobrir_worktrees_do_card so e chamada quando o PROPRIO workspace e git
     (kanban_db.py: `if is_git: candidates.extend(...)`).
     Num card scratch nao-git ela NUNCA roda — independentemente de
     default_workdir, que nem e lido por este codigo.
```

Confirmado no fonte: `kanban_db.py` so aplica `default_workdir` a
`workspace_kind in {"dir","worktree"}` — **nunca a scratch**, que e o kind de
W1. O gate nao le `default_workdir` em lugar nenhum.

Uma limitacao com saida FALSA e pior que uma limitacao declarada, porque convida
a fechar o furo com uma acao que nao tem efeito. **W1 continua aberto** e nao
tem saida de configuracao: fechar exige decidir uma ancora objetiva para card
`scratch` cujo trabalho vive num repo que o board nunca viu — decisao de
desenho, com custo, que cabe ao orquestrador e nao a este card.

### Meu proprio commit nao esta empurrado

```
$ git push -u origin card/t7e6fb387-direto
remote: Permission to NousResearch/hermes-agent.git denied to cytracks-git.
fatal: ... The requested URL returned error: 403
```

Sem permissao de push no repositorio alvo. O trabalho esta commitado em
`721213d0703`, no worktree `~/atlas/wt/t7e6fb387-direto`, rama
`card/t7e6fb387-direto`.

Pelo criterio do **meu proprio gate**, isto e trabalho em risco. Nao forjei um
remoto para contornar — seria exatamente o caso W3 que acabei de documentar.
Fica registrado como pendencia de credencial.

### Custo/cota

**NAO MEDIDO.**
