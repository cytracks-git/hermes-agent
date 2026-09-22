# Recibo do freeze — t_78aaa333

Produção/testes congelados em `351bfa47b3c367727192cedac4a38180fdbd96ad`.
Nenhuma mudança de produção depois da UI positiva/negativa; comparação de 14 arquivos entre lab e worktree em `rodada2-source-hashes.json`, todos `same=true`.

## Regeneração FINAL do objeto Git (sucede a cópia inicial do worktree)

Executado:

    git archive --format=tar --output=.t78-frozen.tar HEAD
    shasum -a 256 .t78-frozen.tar

Saída:

    2775673cdf149c156e5bc400e2ea80f01791b8ef692dcbbe955c15c49241eed4

Container novo `t78-frozen-proof` com o archive somente-leitura, dependências da imagem, `HERMES_TEST_FILE_RETRIES=0` e:

    uid=502 gid=20(dialout) groups=20(dialout)
    test ! -e /tmp/work/.venv <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
    test ! -e /tmp/work/node_modules <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->

Extração: `mkdir /tmp/work && tar -xf /candidate.tar -C /tmp/work`. Nada de venv/node_modules do host. Sem `.git`: o passo auxiliar de precompilação imprime `fatal: not a git repository`; não é o RC do runner nem impediu execução dos testes. Não foi fabricado repositório/base para esconder esse aviso. <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->

Suites COMUNS pelo harness versionado:

    sh /tmp/work/docs/evidencia/t_78aaa333/harness/prova.sh /tmp/work \ <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
      /tmp/work/docs/evidencia/t_78aaa333/harness/alvos-comuns.txt /tmp/proofs frozen-comuns <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->

    rotulo=frozen-comuns rc=0 falhas=0
    Summary: 80 files, 605 tests passed, 0 failed, 4 skipped ... in 22.5s

Integração pelo runner:

    bash scripts/run_tests.sh tests/tools/test_file_approval_worker.py \
      tests/plugins/test_kanban_file_approval_api.py \
      tests/tui_gateway/test_kanban_notify_poller.py \
      tests/tui_gateway/test_diagnostic_notification_presentation.py \
      tests/gateway/test_kanban_notice_copy.py --tb=short -rf -q

    Summary: 5 files, 51 tests passed, 0 failed ... in 36.9s
    rc=0

Mutação: executado `harness/controle_negativo.py` existente, redirecionando apenas seus caminhos fixos RAIZ/HARNESS/SAIDA para `/tmp/work` e `/tmp/proofs/mutantes` via `runpy` (não reescrevendo guardas/testes fora das sabotagens declaradas). Todas as mutações sequenciais, com nenhuma outra suite concorrente nessa árvore. Logs brutos/RC/IDs preservados em `frozen-proofs/mutantes/`. <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->

    BASE (sem sabotagem): rc=0 falhas=0
    N12: rc=1 falhas=5 -> ACUSOU
    RESTAURADO: rc=0 falhas=0
    TODAS as 12 sabotagens foram acusadas, com rc real do runner canonico.
    restored_source_matches=True

A rodada final de mutação JÁ inclui o teste de duas escritas concorrentes; substitui a limitação temporal narrada no primeiro recibo de RODADA2. `restored_source_matches` comparou SHA-256 de cada entrada de `rodada2-source-hashes.json` após a restauração, não só o RC dos testes.

Imagens efetivas:

    atlas-prova-t78:harness
    sha256:ab45d35b943737c7d5065f7459a6596a69fc041e32723d2c2563034022d62ce8
    atlas-appr-dash:t_78aaa333
    sha256:063a5d04fb8e2daa8fa218e7e3957e99d33d14d8b938d77ba85f6d801caf23a3
    node:24
    sha256:7e6ba96b9576ae44872bdb57bc0665a70fd87bbc7c8a019ab849429c6c69ef44

## Segurança e escopo de revisão

Gitleaks no diff staged ANTES do commit: `scanned ~328404 bytes ... no leaks found`, RC0. Nova varredura em TODA evidência incluindo provas congeladas: `scanned ~499453 bytes ... no leaks found`, RC0. Sem tokens vivos nos recibos.

`git diff --cached --check` no código/documentos (excluindo `*.log`) RC0. A execução abrangendo logs acusa espaços à direita na saída bruta de testes; os logs não foram editados para fabricar limpeza. O aviso não se refere ao código.

Filhos inspecionados com kanban_show: `t_5924c6bc` é publicação AGENTS, `t_af463e6a` é regra SOUL, NÃO raias de QA/revisão deste patch. Ambos devem continuar aguardando correção instalada/provada e consentimento fresco. Não houve complete do pai para soltá-los.

Revisão solicitada no próprio card ao perfil `revisor`, com produção/instalação **não liberadas**. C28/C29, lacunas contextuais de produção e decisão sobre Move/Delete/remoto estão explicitamente em RODADA2; não desaparecem por estas suites verdes. Não autoaprovar nem encerrar o card como comportamento instalado.

Limpeza confirmada por readback: containers `t78-approval-ui`, `t78-node-r2`, `t78-frozen-proof` e volume `t78-node-r2` removidos; consultas Docker retornaram vazio para esses nomes. Nenhum container/worker alheio foi encerrado.

O scanner recusou ANTES da execução a limpeza conjunta de `.t78-frozen.tar`, `.t78-old-notifications.py` e `.t78-web-dist/`: `BLOCKED: Security scan — [CRITICAL] Mass file deletion in a short window`. Não reexecutei por outro comando/ferramenta. Esses TRÊS temporários permanecem untracked no worktree e fora do caminho de produção/commit; remoção depende de encaminhamento autorizado do operador. Isso não é regressão do produto nem bloqueio da revisão técnica. Não alegar worktree totalmente limpo.

O commit posterior ao freeze adiciona somente documentação/recibos; o SHA de produção acima é o alvo da revisão técnica.
