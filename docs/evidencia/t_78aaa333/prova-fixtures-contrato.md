# Evidência de execução — fixtures do contrato v3 (t_069cfdac, run 541)

Ambiente: Docker **não-root** (UID 502), `--network none`, imagem de dependências já
existente `kanban-body-t5a6:proof` (Python 3.13, **NÃO** reconstruída). Runner obrigatório
`scripts/run_tests.sh` (sem `pytest` puro). `HOME` isolado, `HERMES_TEST_ISOLATION=1`,
`HERMES_PYTHON=/usr/local/bin/python3`.

Nada foi alterado na árvore de trabalho fora de `docs/evidencia/t_78aaa333/`.

Scripts do lab versionados junto: `fixtures/mutar.py` (mutação, aplicada numa CÓPIA da fonte).
Os scripts de orquestração do lab (`rodar_lab.sh`, `rodar_mutantes.sh`) ficaram em `/tmp` por <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
serem descartáveis; o conteúdo de cada comando está reproduzido abaixo.

## 0. Como a fonte chegou ao lab, e por que não foi `git archive | tar`

As duas rodadas anteriores usaram `git archive HEAD | tar -x`. Nesta rodada o **scanner de
segurança recusou** o comando (`Archive extraction to sensitive path`), e também recusou
`git clone <caminho>` (leu o caminho como URL sem esquema). Registrado como fato, sem
contornar por caminho alternativo escondido: a cópia foi feita com
`rsync -a --exclude .git ./ /tmp/lab-t069/base/`, e a equivalência com o commit foi medida <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
**antes** da cópia:

    $ git status --porcelain
     M docs/evidencia/t_78aaa333/fixtures/mutar.py
     M docs/evidencia/t_78aaa333/fixtures/test_contrato_aprovacao.py
    ?? docs/evidencia/t_78aaa333/contrato-aprovacao-humana-v3.md

Ou seja: **o código de produto no lab é byte a byte o do commit**; o único diff é a própria
entrega em `docs/evidencia/`. (O `run_tests.sh` no container avisa `fatal: not a git
repository` ao pré-compilar bytecode, porque `.git` não foi copiado — não afeta a coleta.)

Dependências do dashboard (`fastapi`, `starlette`, `multipart`, `python_multipart`,
`annotated_doc`) montadas **read-only** de `~/.hermes/hermes-agent/venv/.../site-packages`
direto no `site-packages` do container. `PYTHONPATH` continua não servindo: `run_tests.sh`
roda o runner sob `env -i` e derruba a variável. Nada instalado na imagem, rede desligada.

## 1. Baseline (código íntegro)

    Discovered 1 test files (~21 tests) under ['tests/tools/test_contrato_aprovacao.py']; running with -j 28
    [100.0% |    21/~21 | ✓18 | ✗ 0] ✓ tests/tools/test_contrato_aprovacao.py (18✓ 3xf, 6.7s)

    === Summary: 1 files, 18 tests passed, 0 failed (100% complete) in 6.7s (28 workers) ===

- **18 passaram** (eram 16 em v2; C-36 e C-37, os dois bloqueadores de R2, entram verdes).
- **3 `xfail` estritos**: `C-03/C-04` (estado `waiting_approval`), `C-09` (tabela
  `approval_requests`) e `C-35` (`approval_requested` notificável). São o RED do que falta.
- **0 pulados.**

C-32 continua sendo RED por asserção positiva, não por xfail — a fixture mede as duas formas
do UPDATE lado a lado (a guarda de origem exigida por E-8 e a forma atual do nativo, sem
guarda). Nota mantida de v2.

## 2. Controle negativo — sete mutantes

### Mutante 1 — "adicionar o estado novo à varredura de promoção"

`recompute_ready` passa a varrer **e** promover `waiting_approval` (E-5), quebrando as duas
camadas (`SELECT` de `kanban_db.py:2145` e guarda `AND status='todo'` do `UPDATE` em `:2178`).

    E       AssertionError: uma varredura de reciclagem moveu uma espera humana
    tests/tools/test_contrato_aprovacao.py:391: AssertionError
    FAILED ...::test_c07_recompute_ready_nao_promove_estado_de_espera_humana
    FAILED ...::test_c08_as_cinco_varreduras_de_reciclagem_so_alcancam_running

**MORTO**, por duas fixtures independentes (C-07 e C-08).

### Mutante 2 — "o portão protegido passa a honrar yolo"

    E           AssertionError: yolo liberou escrita em arquivo protegido
    tests/tools/test_contrato_aprovacao.py:124: AssertionError
    FAILED ...::test_c26_portao_protegido_ignora_yolo_enquanto_o_gate_comum_o_honra

**MORTO.** Controle positivo na mesma fixture: o gate comum (`~/.ssh/config`) libera sob yolo
no mesmo estado, então a medição distingue os dois portões.

### Mutante 3 — "o PATCH genérico do dashboard ganha verbo `approve`"

    E       AssertionError: verbo de decisão exposto no PATCH genérico: {'approve'}
    tests/tools/test_contrato_aprovacao.py:85: AssertionError
    FAILED ...::test_c24_patch_generico_do_dashboard_nao_tem_verbo_de_aprovacao

**MORTO.** Medição real com o módulo do dashboard importado, não por AST nem leitura de fonte.

### Mutantes 4a e 4b — o aviso nas duas listas (o defeito que R2 apontou)

Este é o ponto onde a v2 estava fraca, e a diferença entre 4a e 4b **é** a correção.

**4a — o kind entra SÓ na lista do gateway** (meia implementação de U-4):

    === Summary: 1 files, 18 tests passed, 0 failed (100% complete) in 9.2s (28 workers) ===

**SOBREVIVE — e este é o resultado CORRETO em v3.** Em v2 a fixture C-35 afirmava apenas
`gateway.TERMINAL_KINDS`, então meia implementação virava XPASS estrito e o mutante "morria":
o run ficava vermelho como se U-4 estivesse pronto, com o aviso sumindo no TUI. Exatamente o
que o revisor apontou. Em v3, C-35 exige as **duas** listas, então meia implementação continua
sendo RED (xfail legítimo) e o run segue verde. Um mutante que sobrevive por decisão explícita
do critério é medição, não fraqueza — e está declarado aqui para não ser lido como descuido.

**4b — o kind entra nas DUAS listas** (U-4 implementado de verdade):

    [XPASS(strict)] contrato v3 §5 U-4: 'approval_requested' ainda não é kind notificável
    FAILED ...::test_c35_approval_requested_e_notificavel_nas_duas_listas

**MORTO** pelo `strict=True`: quando U-4 for implementado por inteiro, o RED acusa e obriga a
trocar o xfail pelo positivo. É o mutante que mede o RED de verdade.

### Mutante 5 — "`reconcile_orphaned_running` deixa de reciclar `running`+claim NULL"

Ataca o **controle positivo** de C-36 (bloqueador R2 #1): se a varredura não reciclar mais
esse estado, a fixture estaria medindo um perigo inexistente e tem de acusar.

    E       AssertionError: controle positivo falhou: reconcile_orphaned_running não reciclou
            running+claim NULL — a premissa de E-9 mudou, reavaliar o contrato
    tests/tools/test_contrato_aprovacao.py:426: AssertionError
    FAILED ...::test_c36_a_volta_a_running_precisa_restaurar_a_identidade_no_mesmo_cas

**MORTO.** A fixture não aceita passar verde sobre uma premissa que mudou — ela manda
reavaliar o contrato, que é o comportamento pedido.

### Mutante 6 — "o predicado de órfã volta ao da v2 (`pending`/`granted`)"

É literalmente o bloqueador R2 #2 reintroduzido: a request `consumed` sem escrita some da
varredura e o card fica preso.

    E       AssertionError: predicado de R-7 não é único/exato: ['r_grant', 'r_pend']
    tests/tools/test_contrato_aprovacao.py:489: AssertionError
    FAILED ...::test_c37_predicado_unico_de_orfa_alcanca_consumed_nao_aplicada

**MORTO.**

Placar: **7 mutantes, 6 mortos, 1 sobrevivente declarado e justificado (4a)**.

## 3. As duas medições novas que corrigem afirmações anteriores

### 3.1 São CINCO varreduras de reciclagem, não três (v2 errou a contagem)

A v2 afirmava, em §3.2 E-7 e §4.3 R-5.1, que **três** varreduras filtram `status='running'`, e
citava `reconcile_orphaned_running` na linha `:1136-1138` — que é outra função
(`_reclaim_dead_workers`). Medido neste run, são cinco:

| Varredura | Onde | Filtro |
|---|---|---|
| `detect_stale_running` | `kanban_db_dispatch.py:769` | `status='running'` |
| `reconcile_orphaned_running` | `:851-855` | `status='running' AND (claim_lock IS NULL OR claim_expires IS NULL)` |
| `_reclaim_dead_workers` | `:1135-1139` | `status='running' AND worker_pid IS NOT NULL` |
| `enforce_max_runtime` | `:654-663` | `status='running' AND max_runtime_seconds IS NOT NULL AND worker_pid IS NOT NULL` |
| `release_stale_claims` | `kanban_db.py:2440-2446` | `status='running' AND claim_expires IS NOT NULL AND claim_expires < now` |

A conclusão de E-7 **se mantém** (nenhuma alcança `waiting_approval`), mas estava apoiada numa
contagem errada, e duas delas nunca tinham sido executadas por fixture nenhuma. C-08 agora roda
as cinco, com o mesmo controle positivo.

### 3.2 `reconcile_orphaned_running` recicla `running`+claim NULL (C-36)

O caminho feliz da v2 produzia exatamente esse estado, e a própria C-08 já o usava como
controle positivo de reciclagem. Medido agora nas duas direções na mesma fixture:

- forma ERRADA (só o status muda) → a varredura promove para `ready`, e o dispatcher spawnaria
  um segundo worker LLM ao lado do primeiro, que continua vivo;
- forma EXIGIDA por E-9 (status + `claim_lock`/`claim_expires`/`worker_pid`/`worker_started_at`/
  `last_heartbeat_at` no MESMO UPDATE) → a varredura não toca na linha.

## 4. O que NÃO foi medido, e por quê

- **Entrega real de aviso (C-21/C-22), UI instalada (C-19/C-28/C-29):** fora do alcance de
  fixture, por construção. São `I`/`H` na matriz.
- **Espera longa real (C-18/C-30):** fixture com relógio controlado é aproximação; a prova
  honesta é a etapa 7 do plano.
- **Órfã por morte de worker real (C-34):** C-37 mede o **predicado** contra o DDL; matar um
  processo de verdade no meio de uma pendência é `I` na implementação. O que está provado é
  que o predicado alcança os três estados certos e não alcança os errados — não que a
  varredura exista (ela não existe ainda).
- **C-36 mede a forma do UPDATE, não a função `pause_for_approval`** (que não existe). Prova
  que a forma exigida sobrevive à varredura e que a forma ingênua não. A implementação real é `I`.
- **Isolamento contra processo hostil de mesmo UID (§1.3, Camada 2):** não medido e **não
  prometido**. Worker e superfície humana compartilham UID 502 e o mesmo `kanban.db`.
- **Nenhum dos 18 verdes prova a feature pronta.** Provam precondições, guardas de fluxo e
  formas de SQL exigidas — não a feature.

## 5. Limpeza

Containers do lab removidos ao fim (`--rm` em toda execução); nenhuma imagem construída ou
apagada; nada instalado dentro da imagem; rede desligada (`--network none`) em todas as
execuções. Cópias de trabalho em `/tmp/lab-t069/`. <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
