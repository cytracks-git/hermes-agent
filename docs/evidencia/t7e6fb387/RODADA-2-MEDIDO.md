# Gate de evidencia — RODADA 2: o que foi medido

Card `t_7e6fb387`. Este documento cola a saida real. Onde nao houve medicao,
esta escrito NAO MEDIDO.

## Os tres bloqueantes da rodada 1, reproduzidos ANTES de tocar no codigo

O parecer do auditor foi tratado como alegacao ate eu reproduzir. Escrevi
`tests/hermes_cli/test_kanban_evidence_gate_round2.py` e rodei contra o codigo
da rodada 1:

    5 failed, 2 passed in 7.21s

    FAILED ...::test_x2_forged_remote_ref_without_push_is_refused
    FAILED ...::test_x1_scratch_workspace_with_unpushed_external_worktree_is_refused
    FAILED ...::test_x1b_control_declared_external_worktree_pushed_completes
    FAILED ...::test_x3_unreachable_remote_refuses_instead_of_closing
    FAILED ...::test_x3b_control_no_remote_configured_is_also_unmeasured

Os 2 que passam sao controles positivos (leitura pura e SHA real): o gate
antigo ja nao reprovava todo mundo, e o novo tambem nao pode.

### B1 — a autoridade era local, e o worker a escrevia

O gate lia `refs/remotes/*` e `rev-list HEAD --not --remotes`. Um
`git update-ref refs/remotes/origin/<branch> <sha>` forja as duas coisas sem
nenhum push. Medido: o card fechava com a arvore so no disco.

Agora a resposta vem de `git ls-remote`, que o worker nao controla.

### B2 — so o workspace do card era medido

Contagem no board de producao:

    scratch   73
    worktree   5
    dir        3

Os cards `scratch` nao sao repos git; o trabalho vive num worktree FORA do
workspace, declarado em `metadata.worktree` (15 runs ja fazem isso). O gate
antigo nao olhava para la — trabalho invisivel.

Agora mede-se o CONJUNTO (workspace + caminhos declarados), deduplicado por
`git-common-dir`.

### B3 — falha de sonda fechava o card

    except (subprocess.SubprocessError, OSError):
        pass

"Nao consegui medir" virava "esta limpo". Nasce `UnmeasuredEvidenceError`:
nao medir nao e o mesmo que medir e achar limpo.

Junto veio o defeito de INCENTIVO: a mensagem antiga dizia *"remove the commit
field from metadata"*. Declarar o SHA travava, calar fechava — o gate ensinava
a mentir por omissao. A mensagem nova manda commitar/empurrar ou corrigir o
SHA, nunca apagar o campo.

## Os quatro casos que o card exige

Mesmo worktree real, mesmo codigo, remoto git de verdade. A UNICA variavel
entre N1 e P1 e o `git push`.

    === [N1] commit local, rama NAO empurrada ===
    [N1/P1] worktree REAL, rama do card
        -> RECUSOU [UnpushedWorkError]
           completion blocked: 4 commit(s) in /Users/farantes/atlas/wt/t7e6fb387-direto
           branch card/t7e6fb387-direto (HEAD: c2697a33aa78...) are not announced by
           the remote. Run `git push` and retry.

    === PUSH de verdade ===
    c2697a33aa7881e573c3535ae916e567ec21268b	refs/heads/card/t7e6fb387-direto

    === [P1] mesmo card, DEPOIS do push ===
    [N1/P1] worktree REAL, rama do card
        -> FECHARIA (gate nao recusou)

    === [P2] leitura pura: workspace scratch nao-git, sem commit ===
        -> FECHARIA (gate nao recusou)

    === [N2] SHA inventado em metadata ===
        -> RECUSOU [UnknownShaError]
           completion blocked: metadata claimed commit SHA(s) that no measured
           repository can resolve: deadbeef...deadbeef. Commit and push the work,
           or correct the SHA to one that exists.

Reproduz com `docs/evidencia/t7e6fb387/prova-board-real.py`.

### O que e real e o que e isolado nesta prova

REAL: o worktree, os commits, o `git push`, o remoto consultado por rede, e o
codigo do gate como vai para revisao.

ISOLADO: o `kanban.db` (board temporario). Motivo medido, nao de conveniencia:
a sessao worker que roda a prova ja segura o lock do banco de producao, e o
processo ficava em espera indefinida (PID 95106, travado ate ser morto). O
banco nao e o sujeito da medicao; o par (repo, remoto) e.

REMOTO DE ESCRITA: o `origin` real (`NousResearch/hermes-agent`) recusa push
desta credencial —

    remote: Permission to NousResearch/hermes-agent.git denied to cytracks-git.
    fatal: ... The requested URL returned error: 403

Por isso o P1 usa um bare repo local (`/tmp/remoto-prova-p1.git`) como origin,
restaurado ao fim. O `ls-remote` contra o GitHub real continua exercitado em
N1/N2. NAO MEDIDO: push para o GitHub upstream.

## Mutante: a classe do defeito morreu, nao so o caso

Testes NOVOS contra o codigo VELHO (`93d8e373ecd`), mesmo estimulo:

    === MUTANTE: codigo de 93d8e373ecd + testes de HEAD ===
    5 failed, 2 passed in 8.89s

Contra o codigo novo: `7 passed`. Reproduz com
`docs/evidencia/t7e6fb387/mutante-round2.sh`.

## Suite completa

    tests/hermes_cli/test_kanban_evidence_gate.py
    tests/hermes_cli/test_kanban_evidence_gate_round2.py
    tests/tools/test_kanban_tools.py
    -> 53 passed in 29.52s

## Dois defeitos MEUS, achados medindo e corrigidos na mesma rodada

1. **Escala.** O remoto anuncia **118.677 refs** (quase todas `refs/pull/*`)
   contra **1.802** branches. Cobrando ancestralidade ref a ref, o fechamento
   passou de **400s sem terminar** (PID 25797, morto). Corrigido com
   `ls-remote --heads` + filtro em lote + um unico `rev-list`: **3.1s**
   fim-a-fim.

2. **Numero mentiroso.** A recusa dizia `3193 commit(s)` onde havia **3** —
   contava o historico inteiro quando a branch nao existia no remoto. Recusar
   certo com numero errado ainda e mentira, porque e esse numero que o worker
   le. A contagem passa a descontar `refs/remotes`; a DECISAO continua vindo do
   `ls-remote`, entao forjar essas refs so estraga o proprio numero do worker,
   sem fechar o card.

## Contrato mudado, declarado em vez de silenciado

`test_no_remotes_skips_unpushed_gate` -> `test_no_remotes_is_unmeasured_and_refuses`.

A versao antiga fechava o card quando o repo nao tinha remoto: "nao ha com o
que comparar" virava licenca para fechar. Isso e o proprio fail-open que o card
manda matar — commits num repo sem remoto sao exatamente o trabalho que morre
com a maquina. O caminho para fechar esse caso e o `force` do operador (com
controle positivo no teste), nao o silencio do gate.

## Sucesso tambem deixa rastro

Fechamento aprovado grava `completion_evidence_verified` com os repos, branches
e SHAs medidos. Verde sem registro do que se mediu e o falso-verde que este
gate existe para matar.

## check-trabalho-orfao: o que o card pediu e o que da para medir

O card pede `node scripts/check-trabalho-orfao.mjs`. Esse sensor **nao existe
no hermes-agent** (o alvo deste card); ele vive no repo do Atlas
(`~/Downloads/clm360`). Rodado la, acusa **20 achados** — worktrees do Atlas
com commit so no disco e arquivos nao commitados.

NAO MEDIDO: o efeito deste gate sobre esse numero. Sao repositorios diferentes,
e o sensor olha o disco do Atlas, nao o fechamento de cards do board. A
afirmacao "a classe parou de crescer" exigiria medir a mesma populacao antes e
depois, com o gate no ar; isso nao foi feito e nao vou afirmar por analogia.
O que ESTA provado e o comportamento do gate nos quatro casos acima.
