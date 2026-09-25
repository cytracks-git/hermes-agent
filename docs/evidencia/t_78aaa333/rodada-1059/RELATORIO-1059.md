# Rodada 1059 — conserto do achado do R3 (leitura por request) + índice medido

Card: t_78aaa333 · Writer: agente direto (Hermes nativo, perfil arquiteto, Claude OAuth)
Base: 90a45ecc0de · Veredito que originou a rodada: R3 `changes_requested`

## O que o R3 apontou

> `_last_progress` lê `kind = ? ORDER BY id DESC LIMIT 200` e confere o
> `request_id` **depois**, em Python. Com mais de 200 observações de outras
> requests entre duas leituras da mesma, a dedupe fica cega: o poll idêntico
> grava linha nova.

Procedente. Medido, não aceito por leitura.

## Discover — o defeito, medido nas duas árvores

Sonda: `harness/sonda_janela_global.py` (via `harness/sonda-docker.sh`).
Mesmo estímulo dos dois lados: 1 observação da request alvo, 210 observações de
**outras** requests do mesmo card, depois o mesmo poll da alvo.

    ANTIGA (90a45ec)                      NOVA (esta rodada)
    DEDUPE alvo_antes=[3]                 DEDUPE alvo_antes=[3]
    DEDUPE poll_identico_gravou=True      DEDUPE poll_identico_gravou=False
    DEDUPE alvo_depois=[3, 214]           DEDUPE alvo_depois=[3]
    DEDUPE PERDEU_A_REQUEST=True          DEDUPE PERDEU_A_REQUEST=False
    RETRY  reabriu_apos_retry=False       RETRY  reabriu_apos_retry=True
    RETRY  PERDEU_O_RETRY=True            RETRY  PERDEU_O_RETRY=False

O `[3] -> [3, 214]` é exatamente o que o R3 descreveu. A **segunda** linha é
achado novo desta rodada: a mesma janela global também engolia a marca d'água
do `Retry notice` humano — com 200 retries de outras requests no meio, o pedido
de reenvio do operador não reabria o orçamento. O R3 levantou a hipótese; aqui
ela está medida.

Por que a suíte sozinha não bastava como prova: na árvore antiga, 3 dos 5
testes que reprovam falham por **assinatura** (`notice_budget_open` ganhou
`task_id`), não pelo defeito. Falha por assinatura não prova defeito nenhum —
daí a sonda, que chama a função de produção com a assinatura que cada árvore
tem e imprime o que foi observado.

## Govern — o que foi decidido

1. **Predicado por request, em SQL** (`_OF_REQUEST`): `task_id = ? AND kind = ?
   AND json_extract(payload,'$.request_id') = ?`. A request deixa de ser
   filtrada depois de um recorte arbitrário; o recorte deixa de existir.
   Vale para `_last_progress`, `_notice_retry_marker`, `notice_attempts` e
   `_delivery_view` — todos os quatro pontos de leitura, não só o citado.
2. **`task_id` passa a ser exigido** nessas funções. Antes a leitura cruzava
   cards; a única chamadora externa (`tui_gateway/session_notifications.py`)
   já tinha o `task_id` em mãos.
3. **Índice `idx_events_task_kind(task_id, kind, id)`** — decidido **depois**
   de medir, não junto com o patch (ver Prove).

## Act — o que mudou

    hermes_cli/kanban_approval_diagnostics.py   +135/-84  leitura por request
    hermes_cli/kanban_db.py                     +7        índice no SCHEMA_SQL
    hermes_cli/kanban_db_connect.py             +8/-4     índice no _REBUILD_SPECS
    tui_gateway/session_notifications.py        +3/-2     chamada com task_id
    tests/hermes_cli/test_kanban_approval_diagnostics.py  +110  3 guardas novas
    tests/hermes_cli/test_kanban_db.py          +62       sensor de reconstrução

## Prove — o custo do conserto, medido (e uma correção de rumo)

No plano eu escrevi "sem índice novo". **Estava errado, e a medição é que
mostrou.** `harness/sonda_custo_leitura.py`, 5.003 linhas:

    plano_nova:   SEARCH task_events USING INDEX idx_events_task (task_id=?)
                  USE TEMP B-TREE FOR ORDER BY        <-- ordena TUDO do card
    plano_antiga: SCAN task_events
    nova=2,177 ms/leitura (achou=True) · antiga=0,285 ms/leitura (achou=False)

A antiga era "rápida" porque **não achava** o alvo — é o defeito, não
desempenho. Ainda assim, 7,64x é custo real. Escala medida (`razao_nova/antiga`):
103 linhas 0,37x · 403 linhas 0,62x · 1003 linhas 1,54x · 5003 linhas 7,64x.

O board real da Atlas hoje: 229 cards, maior card **1.395 eventos**
(`sqlite3 ~/.hermes/kanban/boards/atlas/kanban.db`). Ou seja: a faixa onde a
leitura nova já é mais cara **é o tamanho de hoje**, não um cenário distante.

`harness/sonda_indice_candidato.py`, card de 1.403 eventos, os dois casos:

    alvo é a request MAIS RECENTE do card (o caso de produção):
      SEM_INDICE  USE TEMP B-TREE FOR ORDER BY   0,603 ms/leitura
      COM_INDICE  SEARCH ... idx_events_task_kind 0,007 ms/leitura   (86x)

    alvo é a MAIS ANTIGA (pior caso, ORDER BY id DESC varre todas as irmãs):
      SEM_INDICE  0,620 ms/leitura
      COM_INDICE  0,662 ms/leitura                                   (empate)

Decisivo no caso de produção, nunca pior. Por isso o índice entrou.

### O que o índice destravou por tabela

`DROP TABLE` leva os índices junto, então um índice novo no `SCHEMA_SQL` que
não seja repetido no `_REBUILD_SPECS` **some calado** em qualquer board legado
reconstruído. Três comentários no `kanban_db_connect.py` diziam que um teste
chamado `test_rebuilt_schema_matches_fresh` guardava isso.

**Esse teste não existia em lugar nenhum da suíte.** A promessa estava no
comentário; a cobertura, não. Comentário desatualizado é mentira (regra 11):
o sensor foi escrito
(`test_a_rebuilt_legacy_board_ends_up_with_the_same_schema_as_a_fresh_one`),
os três comentários foram corrigidos para o nome real, e a sabotagem **M10**
prova que ele tem dente.

## Provas (Docker, uid 502:20, --network none, regra 12)

Imagem `atlas-prova-t78:harness`; runner canônico `scripts/run_tests.sh` via
`harness/prova.sh`; rc lido de **arquivo**, nunca de pipe.

    recorte 1057/1058   6 arquivos    87 testes    0 falhas   rc=0
    comuns (regressão) 80 arquivos   606 testes    0 falhas   rc=0
    kanban amplo      106 arquivos  1091 testes    1 falha*   rc=1
    controle negativo  10 sabotagens 10 ACUSARAM   base rc=0, restaurado rc=0

\* `tests/tools/test_approval.py::test_redirect_to_sensitive_target` — **falha
igual em 90a45ec sem o patch** (medido), não é regressão desta rodada. Virou
achado próprio, abaixo.

Guardas novas (todas nomeadas pelo comportamento, contrato e não retrato):

    test_an_unchanged_wait_stays_silent_however_busy_the_board_gets
    test_a_human_retry_marker_is_not_lost_behind_other_requests
    test_the_projection_reads_this_requests_phase_not_the_boards_last_window
    test_a_rebuilt_legacy_board_ends_up_with_the_same_schema_as_a_fresh_one

## Erguer a régua — achado de segurança, FORA do escopo deste card

Investigando a falha pré-existente, `harness/sonda_redirect_sensivel.py`:

    no macOS (host):
      OK  'cat key >> /Users/farantes/.ssh/authorized_keys'
          chave='access to SSH keys (Windows path)'      <-- casou por ACIDENTE

    homes plausíveis:
      OK         /Users/alguem/.ssh/authorized_keys   (padrão de WINDOWS)
      NAO_PEGOU  /home/alguem/.ssh/authorized_keys
      NAO_PEGOU  /root/.ssh/authorized_keys

`tools/approval_detection.py:20` só reconhece `~`, `$HOME`, `${HOME}`; o
caminho ABSOLUTO de um home Linux não é reconhecido por padrão nenhum. O teste
passa no macOS porque `/Users/...` casa com o padrão de **Windows**
(`approval_detection.py:259`) — acidente de grafia, não cobertura.

Consequência medida: em host Linux, `cat key >> /home/user/.ssh/authorized_keys`
**não** é marcado como perigoso.

Não consertei aqui de propósito: é outra frente (superfície de aprovação, chapéu
CISO), e emendar segurança num card de diagnóstico de Kanban é exatamente o que
a regra 7 proíbe. Custo/risco para o H1 decidir:

- **Risco de não fazer:** escrita em `authorized_keys` sem aprovação em
  qualquer host Linux — inclui os containers do próprio laboratório.
- **Custo de fazer:** baixo no padrão (aceitar `/home/<x>/.ssh` e `/root/.ssh`),
  **médio na validação** — mexer em detecção de perigo pede controle negativo
  próprio e varredura de falso-positivo em toda a suíte de aprovação.
- **Armadilha:** o teste atual é dependente de host (usa `Path.home()`), então
  passa no macOS e reprova no Linux. Consertar o padrão sem consertar o teste
  deixa a cobertura escolhendo o resultado pelo sistema operacional.

## O outro lado da conta: o índice custa quanto?

Ganho de leitura sem o custo de escrita é meia verdade — `task_events` é tabela
de append, e cada evento de cada card passa por ela.
`harness/sonda_custo_escrita.py`, 2.000 eventos por rodada, mesmo processo:

    SEM_INDICE  ms_por_insert=1,4390  bytes_db=774.144  bytes_indice=0
    COM_INDICE  ms_por_insert=1,6612  bytes_db=868.352  bytes_indice=94.208

Ou seja: **+0,22 ms por INSERT (+15%)** e **+94 KB por 2.000 eventos**
(~47 bytes/evento). Contra o ganho de leitura de 0,603 -> 0,007 ms num card de
1.4 mil eventos.

A conta fecha porque as duas pontas têm frequências diferentes: o INSERT
acontece uma vez por observação **material** (a dedupe justamente impede que
polls repetidos gravem), enquanto a leitura acontece em **todo** poll de toda
espera humana. O H1 tem o número dos dois lados para discordar, se for o caso.

## Como reproduzir

    H=docs/evidencia/t_78aaa333/harness
    sh $H/arvore-de-prova.sh . /tmp/arvore        # cópia; o worktree não é exposto <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
    sh $H/prova-docker.sh    /tmp/arvore /tmp/out $H/alvos-1057.txt recorte <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
    sh $H/prova-docker.sh    /tmp/arvore /tmp/out $H/alvos-comuns.txt comuns <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
    sh $H/negativo-docker.sh /tmp/arvore /tmp/out     # 10 sabotagens <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
    sh $H/sonda-docker.sh    /tmp/arvore NOVA         # o defeito do R3 <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
    sh $H/indice-docker.sh   /tmp/arvore 1400 200 fim # o índice <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
    sh $H/custo-docker.sh    /tmp/arvore 5000 200     # o custo <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
    sh $H/redirect-docker.sh /tmp/arvore              # o achado de segurança <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
    sh $H/escrita-docker.sh  /tmp/arvore 2000         # o custo de escrita <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->

## O que NÃO foi medido

- **Concorrência**: todas as medições são de um processo só. O board real tem
  dispatcher, gateway e workers no mesmo arquivo SQLite; contenção de lock não
  foi medida e não afirmo nada sobre ela.
- **Tela**: o recorte é de banco e worker, sem UI — nenhuma prova de interface
  nesta rodada, e nenhuma é alegada.
- **dbstat**: o número de bytes do índice veio do módulo `dbstat` da imagem do
  laboratório; se ele faltar noutro ambiente, a sonda imprime 0 em vez de
  estimar.
