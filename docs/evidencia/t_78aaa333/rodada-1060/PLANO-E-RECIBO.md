# PLANO-E-RECIBO — rodada 1060 (t_78aaa333)

Writer: arquiteto / Claude OAuth (rota nativa Hermes, sem wrappers ask-*/dev-*).
Acceptor: H1. Reviewer: revisor (independente, ainda NAO executado).
Autorizacao desta etapa: comentario 1073 (H1, 1789940500) — "so DEPOIS instalar/provar
Desktop (C28/C29)" — e o `changes_requested` da run 572, que cobra o miolo do CORPO:
"Fecho exige comportamento instalado comprovado, nao somente patch/testes".

SDD lido do objeto git canonico em /Users/farantes/atlas/repos/genesis:
`origin/main:specops/CYTRACKS-SDD-v4.0-RC.md` — 317 linhas, sha1
8fc4a63af6144b81546f223e2dd5f23c038f5c4c. Pin confere.

## RACI (escrito antes de agir)

| Papel | Quem | O que |
|---|---|---|
| A/R | Writer arquiteto | Discover do orfao, promocao da instalacao, recarga do gateway |
| C | PM/Rel (orquestrador) | Janela e drenagem |
| C | CISO | Nenhuma fronteira nova: instalar NAO cria grant de aprovacao |
| C | db-analyst | Esquema do board compartilhado |
| I → R | QA/CISO (revisor) | Revisao independente APOS esta entrega |
| Acceptor | H1 | Aceite; C29 depende de gesto humano real |

Ninguem assina o proprio trabalho. Nenhum `decided_by=H1` foi escrito por mim.

## Discover — o achado que reinterpreta 4 rodadas

As runs 566/567/568/572 afirmaram "patch NAO instalado" medindo
`grep -c waiting_approval` no arquivo da INSTALACAO. Alvo errado para a pergunta
"qual codigo roda".

O dispatcher inicia o worker com `python -m hermes_cli.main` e `cwd` = workspace do
card. Com `-m`, o CPython poe o cwd em `sys.path[0]`; como o workspace deste card E um
checkout do Hermes, o pacote do WORKTREE sombreia o da instalacao.

Medido por `harness/sonda_origem_do_codigo.py`, com o launcher real:

    com_cwd  hermes_cli -> /Users/farantes/atlas/wt/kanban-aprovacao-interativa/hermes_cli/__init__.py
    sem_cwd  hermes_cli -> /Users/farantes/.hermes/hermes-agent/hermes_cli/__init__.py
    marcador waiting_approval: worktree=9  instalacao=0

Consequencia no board REAL: ele ja tinha `approval_requests`,
`idx_appr_one_pending_per_run` e `idx_events_task_kind` — esquema escrito por workers
desta arvore — enquanto gateway/dispatcher/Desktop carregavam a instalacao, que NAO
conhecia o status. Um lado do contrato existia, o outro nunca soube: classe ORFAO.

### Dano medido nas duas arvores

Docker `--rm --network none`, uid 502:20, arvores montadas `:ro`, banco descartavel
dentro do container. Sondas: `sonda_status_desconhecido.py`, `sonda_coluna_do_painel.py`.

| | ANTIGA (d7ea741) | NOVA (643ffa7) |
|---|---|---|
| conhece `waiting_approval` | false | true |
| listar/filtrar por esse status | ValueError | devolve o card |
| coluna no `/board` REAL | `todo` | `waiting_approval` |
| `pause_for_approval` + `resume_from_pause` | ausente | presente |

Controle positivo em toda medicao: card `blocked` no MESMO banco, mesmo estimulo → cai
em `blocked` nas duas arvores. Sem ele, a sonda mediria a propria montagem.

O que NAO acontece (medido para nao inflar o achado): `recompute_ready` nao mexe no card
parado, o filho NAO promove indevidamente, o card nao some das listagens sem filtro. O
dano real e o do card: o pedido fica invisivel COMO ESPERA. `approval_requests` tinha 0
linhas — a janela estava fechada por sorte, nao por desenho.

## Act — o que foi feito, na ordem real

1. Snapshot ANTES (`snapshot-antes.txt`, instrumento `harness/snapshot-instalacao.sh`).
2. Promocao da instalacao: `git -C ~/.hermes/hermes-agent checkout --detach 643ffa7a82c`.
   Fast-forward, 8 commits. O unico arquivo nao rastreado (`hermes_cli/kanban_quota.py`,
   alheio a este card) nao existe no freeze e ficou intacto.
3. Recarga do gateway: SIGUSR1 (drain-aware) → SIGTERM → reposicao pelo launchd.
4. Readback POR PROCESSO (`snapshot-depois-recarga.txt`).

### Recibo da recarga (sequencia real, com os erros)

    21:34:15  SIGUSR1 em 31800. Teardown completo: drain 0.00s (active_at_start=0),
              adapters desconectados, SessionDB fechado, "Gateway stopped (0.15s)".
              gateway_state -> stopped. O PROCESSO NAO SAIU.
              sample: main thread presa em kevent; nenhuma entrada de saida em
              gateway-exit-diag.log (o os._exit nunca foi alcancado).
    ~21:41    `hermes gateway restart` travou; estourou 420s sem retorno.
    21:47:49  SIGTERM. Recebido e logado ("Received SIGTERM — initiating shutdown").
              Meu script desistiu aos 90s e relatou falha.
    21:52:50  O processo saiu por conta do SIGTERM; o shim viu o filho morrer; o
              launchd repos o servico. pid 78236, code_sha 643ffa7a82c.

**Nenhum SIGKILL foi enviado a processo algum.** O degrau de SIGKILL chegou a ser
invocado e nao teve alvo ("No such process") — o processo ja havia saido. O que faltou
foi paciencia no MEU instrumento (90s para um teardown de 13 min), nao forca no sinal.

### Readback por processo (criterio do corpo do card)

    ANTES   pid=31800  code_sha=d7ea741ae04e79fb61b48761af489306b13f1e4a
    DEPOIS  pid=78236  code_sha=643ffa7a82c0e2b8491bee7d31f2495242fb3075  state=running
    launchctl: ai.hermes.gateway -> 78235 (shim) -> 78236 (gateway)

Controle do que nao podia quebrar: worker desta run (56467) vivo do inicio ao fim;
`task_runs` 577 antes e depois; `approval_requests=0`; nenhum card perdido.

## ERROS MEUS NESTA RODADA (registrados, nao diluidos)

1. **Sequencia invertida.** Promovi a arvore no disco com o gateway VIVO carregando a
   antiga. Nao tenho prova de que causou o teardown lento — os modulos do caminho de
   desligamento nao mudaram entre os dois SHAs (`git diff --name-only d7ea741..643ffa7`
   neles e vazio) — mas tambem nao tenho prova de que nao causou, e foi a minha ordem
   que tornou a duvida possivel. O correto era drenar e so entao promover.
2. **Rotulo mentiroso.** Chamei o `git checkout --detach` de "a seco (dry)" no meu
   proprio eco. Nao era dry-run: executou e moveu a instalacao.
3. **Alarme precipitado.** Publiquei "ATO 2 FALHOU" quando o que havia falhado era a
   janela de espera do meu script.
4. **SHA digitado a mao.** O primeiro snapshot imprimiu "NAO-ANCESTRAL" por erro de
   transcricao nos ultimos digitos. Instrumento corrigido para ler os dois SHAs em
   tempo de execucao; o real e FAST-FORWARD, 8 commits.

## Prove — o que esta provado e o que NAO esta

PROVADO:
- Gateway vivo servindo 643ffa7 (readback por processo, nao leitura de disco).
- A arvore instalada serve a coluna `waiting_approval` no `/board` REAL (sonda no
  Docker contra a propria arvore da instalacao, com controle positivo).
- Board integro atraves da janela.

**NAO PROVADO — e por isso C28 nao fecha aqui:**
O Desktop NAO tem o codigo novo, e restart nao resolve:

    app.asar empacotado 19/09 13:31 · grep waiting_approval no bundle = 0
    marcador do painel desta rodada (notice-retry / retryApprovalNotice) = AUSENTE
    desktop-build-stamp.json: builtAt 2026-09-17, sourceMode=false
    backend `serve` (pid 56920) subiu 21:01:48, ANTES do checkout (21:31:28)

O renderer e um bundle Electron congelado: o painel novo so chega com REBUILD
(vite + empacotamento + swap do app.asar), nao com restart. `main_desktop.py` descreve
esse swap como passo que, interrompido, deixa o renderer rasgado e o app morre no
primeiro import preguicoso.

Nao disparei o rebuild por conta propria: esta alem do que o H1 autorizou em 1789940500,
arrisca deixar o operador sem interface, e eu ja errei a sequencia uma vez nesta rodada.

C29 (gesto real do H1 numa operacao verdadeira) continua dependendo de consentimento
fresco e NAO foi simulado.

## ERGUER A REGUA — causa raiz que o rollout NAO resolve

O sombreamento `sys.path[0]` = workspace vale para QUALQUER card cujo workspace seja um
checkout do Hermes (14 `worktree` + 25 `dir` neste board). Depois desta instalacao as
duas arvores coincidem e o sintoma some, mas o mecanismo continua: o proximo worktree
com codigo diferente volta a servir codigo nao revisado ao board compartilhado.

Conserto candidato: spawnar o worker com `-P` (ou `PYTHONSAFEPATH=1`) para o cwd nao
entrar no `sys.path`. Custo ~1-2h mais prova de que nenhum card depende de importar do
proprio workspace. Risco medio: muda o launcher de todos os cards. Frente propria,
decisao do H1 — nao emendo aqui.

## Instrumentos versionados (regra 12-E)

    harness/sonda_origem_do_codigo.py      de qual arvore o worker carrega o codigo
    harness/sonda_status_desconhecido.py   o que o codigo antigo faz com o status novo
    harness/sonda_coluna_do_painel.py      em que coluna do /board REAL o card cai
    harness/arvore-docker.sh               roda uma sonda numa arvore :ro no Docker
    harness/orfao-docker.sh                idem, especifico da sonda do orfao
    harness/snapshot-instalacao.sh         mesmo instrumento nos dois lados da janela
    harness/recarrega-gateway.sh           SIGUSR1 drain-aware + readback
    harness/sigterm-gateway.sh             segundo degrau, com limite explicito
    harness/sigkill-gateway-travado.sh     ultimo degrau (invocado, sem alvo)

## Proximo passo

`request_review(reviewer='revisor')`. Sem `kanban_complete` deste pai: completar
liberaria t_5924c6bc/t_af463e6a, e o Desktop ainda nao exibe o painel. A decisao sobre
o rebuild do Desktop vai ao revisor/H1 com custo e risco, em vez de ser tomada por mim
no meio da janela.
