# t_78aaa333 — rodada 1057/1058: diagnóstico contextual da espera

## Govern: quem decidiu, quem executou, o que foi autorizado

Writer: `arquiteto` / Claude OAuth nativo do Hermes, run 557. Substituto declarado
do `executor`/Codex, que bateu cota 429 — a regra do H1 (comentário 1789940829)
aceita mesma família/modelo para não represar a fila, e esta é a condição real,
sem fingir diversidade. QA/CISO: revisor independente, **ainda não executado**.
PM/Rel: orquestrador. Acceptor: H1, único aprovador humano. A autoria não revisa
a própria entrega nem preenche aceite humano.

SDD lido do objeto Git canônico `origin/main:specops/CYTRACKS-SDD-v4.0-RC.md` no
clone autorizado `/Users/farantes/atlas/repos/genesis`: **317 linhas / SHA-1
`8fc4a63af6144b81546f223e2dd5f23c038f5c4c`** (pin confere).

Recorte autorizado: exatamente o que o comentário 1789940500 liberou — implementar
o diagnóstico contextual no MESMO card, pela proposta já fechada em
`retomada550/PLANO-E-RECIBO.md`. Nenhum card filho criado. Nenhum `ask-*`/`dev-*`.
Nenhuma API paga por token. Nenhuma alteração da instalação compartilhada
(`d7ea741a`). Nenhum arquivo AGENTS/SOUL real tocado. Custo monetário: indisponível.

## Act: o que mudou

**Novo** `hermes_cli/kanban_approval_diagnostics.py` — observação + projeção.
A regra central: **evento só nasce quando muda etapa, motivo, evidência ou
tentativa.** Passagem do relógio nunca cria linha, porque o H1 corrigiu
explicitamente a proposta de alarme de 5 minutos (1058): relógio isolado não
caracteriza defeito. Um worker que faz mil polls na mesma espera grava uma linha.

`tools/file_approval_worker.py` — `apply_granted` passa a devolver
`(resultado, motivo_da_recusa)`. Antes devolvia `None` para **cinco** causas
distintas (lock do dispatcher, teto do board, teto do host, pressão de memória,
teto por perfil) e ninguém registrava qual. O motivo é avaliado **dentro do mesmo
lock** que produziu a recusa (`_admission_refusal`), não recalculado depois: com o
lock na mão ninguém mais escreve, então a contagem é o mesmo retrato. Quando
nenhum teto fecha na releitura, o motivo é `resume_reason_not_yet_observed` — a
recusa foi corrida, e nomear um culpado plausível seria adivinhação.

`tui_gateway/session_notifications.py` — a entrega do aviso ganha orçamento
durável por **geração de transporte**. Antes o laço rebobinava o cursor e tentava
para sempre contra uma conexão morta. Esgotar o orçamento **não decide, não
cancela, não redespacha a escrita**: só para de bater na mesma porta até uma
reconexão real (objeto de transporte novo ⇒ geração nova ⇒ orçamento novo) ou um
`Retry notice` humano. O cursor continua rebobinado em toda falha — nada de
recibo sem entrega.

`plugins/kanban/dashboard/approval_api.py` — `GET /approvals` anexa a projeção
`diagnostics` ao lado do registro imutável (payload e hash seguem byte a byte
iguais); `POST …/notice-retry` reabre o orçamento de aviso sob o **mesmo
principal humano** do endpoint de decisão (credencial de serviço continua
recusada).

UI (desktop `approval-panel.tsx` + web `dist/approvals.js`): bloco
`Wait diagnostics` com etapa, próxima ação, última transição, última evidência,
estado de entrega e custo. Textos em inglês (regra 12-G), comentários em pt-BR.

`hermes_cli/config_defaults.py` — `kanban.approval_notice_max_attempts: 3`. É
config em `config.yaml`, não `HERMES_*` no `.env`: não é segredo.

### Três lugares onde a saída honesta foi preferida à confortável

- `resource_cost` sai `None` e a UI escreve **"Unavailable (not measured)"**.
  CPU/E-S da espera não é medido em produção; zero seria a mentira confortável.
  Há teste de UI que reprova se virar `0`.
- O rótulo de entrega é **"Transport acknowledged"**, nunca "read"/"Human read".
  Recibo de transporte prova que o frame saiu, não que alguém leu. Teste de UI
  reprova a palavra `read` no bloco.
- `granted` sem observação exibe **"the worker has not reported an admission
  attempt yet"**, não "capacidade cheia".

## Prove: saídas reais

Tudo pelo runner canônico `scripts/run_tests.sh` dentro do Docker
(`atlas-prova-t78:harness`), rc lido de ARQUIVO, sem pipe. Host sem venv com
pytest — por isso o Docker, conforme a regra 12.

### Suíte do recorte — `recorte-1057.log` / `.rc`

    === Summary: 6 files, 82 tests passed, 0 failed, 2 skipped (100% complete) in 33.3s
    rc=0

### Regressão nos mesmos 80 alvos da rodada anterior — `comuns-1057.log` / `.rc`

    === Summary: 80 files, 605 tests passed, 0 failed, 4 skipped (100% complete) in 22.8s
    rc=0

Mesmo denominador da `RODADA2.md` (605/605): o recorte não regrediu nada.

### Controle negativo Python — `mutantes-1057.log` / `.rc`

Sete sabotagens, cada uma desfeita antes da próxima, com base e restauração verdes:

    === BASE (sem sabotagem): rc=0 falhas=0
    M1 deduplicacao ignora a etapa                      -> ACUSOU
    M2 deduplicacao some (observacao nasce do relogio)  -> ACUSOU
    M3 granted sem observacao alega capacidade cheia    -> ACUSOU
    M4 orcamento de aviso vira ilimitado                -> ACUSOU
    M5 orcamento deixa de ser por geracao               -> ACUSOU
    M6 retry humano para de reabrir o orcamento         -> ACUSOU
    M7 diagnostico entra na lista de notificacao        -> ACUSOU
    === RESTAURADO: rc=0 falhas=0
    TODAS as 7 sabotagens foram acusadas, com rc real do runner canonico.

**M1 nasceu vermelha por defeito meu, não por acaso.** Na primeira execução ela
passou em silêncio: eu não tinha teste cobrindo "a etapa mudou". Sem isso, uma
transição de `awaiting_human` para `awaiting_admission` deixaria de gravar e o
painel mostraria a etapa anterior para sempre. Corrigi com
`test_each_material_change_produces_exactly_one_new_observation`, que exercita
etapa, motivo e tentativa isolados. O buraco está registrado aqui porque um
controle negativo que só confirma o que já se acredita não mede nada.

### Controle negativo de UI — `ui-mutante-u1..u3.log`

    U1 custo nao medido vira 0          -> ACUSOU
    U2 Retry notice aparece sempre      -> ACUSOU
    U3 bloco renderiza sem projecao     -> ACUSOU
    RESTAURADO                          -> VERDE

### UI e build

    ui-unit-1057.log:  Test Files 3 passed (3) · Tests 39 passed (39) · rc=0
    tsc-1057.rc:       0   (tsc -p apps/desktop --noEmit, saida vazia)
    web-build-1057.log: built in 3.06s · rc=0

### Servidor real, com conferência externa — `servidor-real-1057.log`

Router de produção + gate humano de produção, banco e workspace descartáveis,
lifespan desligado para não acordar provedores/gateway/dispatcher. Seis passos,
com o JSON real colado no log:

1. `pending` → `awaiting_human`, ação "Approve or deny this exact content";
   `resource_cost: null`.
2. `granted` sem observação → `resume_reason_not_yet_observed`.
3. Com a observação que o worker grava sob o lock → `board_capacity` +
   "raise kanban.max_spawn".
4. Três falhas de entrega → `exhausted`, rótulo "Delivery failed; budget
   exhausted", sem a palavra "read".
5. `POST /notice-retry` reabriu o orçamento e **não** mexeu em
   `state`/`decided_by`/`applied_at`.
6. Conferência por fora da API:

       externo: AGENTS.md = b'old\n'
       externo: eventos por kind: [('approval_granted', 1), ('approval_notice_retry', 1),
                                   ('approval_progress', 5), ('approval_requested', 1),
                                   ('claimed', 1), ('created', 1), ('spawned', 1)]

O alvo continua `old\n`: diagnóstico é observação, não escreveu byte nenhum.

## Defeito do harness encontrado e corrigido nesta rodada

A primeira execução rodou **a suíte inteira (~44 mil testes)** em vez do recorte.
Causa: `prova.sh` validava a lista de alvos com `[ -s "$ALVOS" ]`, e um bind mount
de caminho inexistente cria um **diretório** — que tem tamanho > 0 e passava no
teste. A lista saía vazia e o runner rodava tudo, sem erro nenhum. Corrigido para
`[ -f ]` + `[ -s ]`, com o motivo no comentário do script. Um log contaminado por
essa execução foi descartado e a prova foi refeita em diretório limpo; os
artefatos aqui são os da execução limpa.

## Erguer a régua: o que esta rodada NÃO fechou

| Frente | Estado medido | Custo/risco de fechar |
|---|---|---|
| Entrega ao Desktop Electron instalado e resposta do H1 (C28/C29) | **NÃO MEDIDO**. Só servidor real + unit. | Depende de rollout/drenagem e consentimento fresco; não estimável sem decisão do H1. |
| Custo de CPU/E-S da espera longa | **NÃO MEDIDO**. A UI declara isso. | Precisa de medição em lab com espera longa real; 2–4 h, risco baixo. |
| Diagnóstico por evento no gateway de mensageria (Telegram etc.) | Fora do recorte. O aviso só foi medido no TUI. | Precisa decisão: qual superfície mostra `Retry notice`. |
| `resume_reason_not_yet_observed` em corrida | Classificado como não observado. Correto, mas não distingue "corrida" de "worker morto". | Fechar exige heartbeat correlacionado; frente própria. |
| Fronteira contra agente com as mesmas credenciais do humano | **NÃO DEMONSTRADA** (herdado da RODADA2). | Revisão CISO antes de instalar. |

Risco de espera técnica prolongada em produção **continua existindo**: esta rodada
dá ao operador o motivo e a próxima ação, não elimina a espera. Não recomendar
rollout como protegido contra esse risco com base nestas provas.

## Freeze / revisão

Delta congelado em commit revisável junto com as evidências. Revisão por outro
agente/sessão no Kanban, nunca autoaprovação. Instalação, publicação e aceite H1
permanecem **zero**. Ferramentas e regras desta rodada (`ui-diagnostico-1057.sh`,
`controle_negativo_1057.py`, `alvos-1057.txt`, correção do `prova.sh`) vão para o
repositório **no mesmo commit**, conforme a regra 12-E.
