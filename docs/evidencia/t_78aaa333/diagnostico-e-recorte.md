# t_78aaa333 — diagnóstico e recorte estrutural para decisão

Estado: DISCOVER reproduzido; implementação integrada NÃO entregue. O desenho de UX foi aprovado pelo H1 durante este run. Esta nota NÃO solicita novamente autorização de escopo nem constitui consentimento para editar AGENTS/SOUL.

## Base, papéis e freeze

- Worktree exclusivo: `/Users/farantes/atlas/wt/kanban-aprovacao-interativa`.
- Branch: `executor/kanban-aprovacao-interativa`; base `d7ea741ae04e79fb61b48761af489306b13f1e4a`.
- SDD canônico lido via objeto Git: 317 linhas; SHA-1 `8fc4a63af6144b81546f223e2dd5f23c038f5c4c`.
- Writer: executor, GPT-6-Astra nativo, provider openai-codex/OAuth. Nenhum wrapper/agente externo foi iniciado. Custo financeiro indisponível.
- RACI: implementação executor R/orquestrador A; QA e CISO revisor independente R/A; PM e freeze de release orquestrador R/A; aceite e resposta humana H1 R/A. Família do revisor não presumida; ninguém assina sua autoria.
- Freeze do Writer: sem rollout, sem reload, sem alteração na instalação compartilhada, nos alvos protegidos, nas permissões ou no schema. O Rel precisa autorizar a futura implantação após revisão.

## Causa reproduzida, sem LLM

`cli.py:3025` registra `_approval_callback`. O worker Kanban é iniciado com `stdin=DEVNULL` em `hermes_cli/kanban_db_dispatch.py:2844`. A guarda protegida, sem callback gateway, chama o callback CLI (`tools/file_tools_write_guards.py:307-318`). O callback em `hermes_cli/cli_modal_mixin.py:772` não rejeita a ausência de `_app` antes de abrir a espera de modal.

Em Docker não-root, com imports reais e fixture sem UI (prazo reduzido somente no teste):

    BLOCKED: write to protected agent-instruction file(s) (AGENTS.md) approval prompt timed out without a user response. Silence is not consent. The user has NOT consented to this write. Do NOT retry it or attempt the same edit via another path (terminal, execute_code, etc.).
    elapsed=1.102s paints=2 UI=None request_id=ABSENT

A fixture não escreveu AGENTS/SOUL. A camada CLI esperou um modal sem aplicação, antes de criar qualquer requisição JSON-RPC para o desktop. Isto prova esse caminho sem UI, não um clique humano E2E.

Leitura somente de `kanban_notify_subs` no board real confirmou origem TUI/perfil default comum para este card e os dois alvos. Comentário no card não alimenta o callback.

## Regeneração e controles

Fonte regenerada com `git archive HEAD` num novo `/tmp/lab` dentro de container descartável, rede desativada e UID/GID do host (não-root). Extraído apenas o teste RED do arquivo preservado. Runner obrigatório `scripts/run_tests.sh`; sem bare pytest. <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->

Saída real em `regeneracao-red.log`:

    === Summary: 2 files, 79 tests passed, 0 failed (100% complete) in 7.3s (28 workers) ===
    === Summary: 1 files, 0 tests passed, 1 failed (100% complete) in 2.4s (28 workers) ===
    AssertionError: timeout
    RED_EXIT=1 (expected 1)

Os 79 testes são os controles existentes em `tests/tools/test_file_write_safety.py` e `tests/hermes_cli/test_cli_approval_ui.py`: incluem permissões/recusas e UI de aprovação em fixtures. NÃO constituem GREEN da feature nova. O RED exige que um callback sem canal humano reporte indisponibilidade, em vez de aguardar um modal inexistente.

A imagem de dependências já disponível foi `kanban-body-t5a6:proof`; NÃO houve rebuild dessa imagem. Houve reconstrução da fonte e do lab em container novo. Primeira execução em bind mount teve aviso de worktree Git externo/cache read-only; a regeneração posterior eliminou esses problemas. A regeneração conservou avisos de metadados tar do macOS e de pytest-asyncio.

Não há sensor corrigido nem mutante de correção a declarar. Não há prova humana real, teste de espera longa, persistência instalada, migração ou retomada verde.

## Decisão H1 incorporada — contrato de UX

- Coluna própria `Waiting approval`, separada de `Blocked`.
- Card destacado, motivo, arquivo e alteração exata; ação humana `Approve this change`, inicialmente desmarcada; negar/cancelar disponíveis.
- Contador de pendências no topo do board e aviso na conversa de origem, com recibo de entrega (enfileirar não é entregar).
- Pendência durável até decisão, inclusive após fechar/reabrir UI; não ocupa LLM/slot de worker e não entra em respawn-loop, triage ou falha por demora humana.
- Timeout do processo e validade da solicitação são conceitos separados. Um gesto humano para a mesma operação, sem popup redundante.
- Autorização de uso único, vinculada a payload/hash/escopo; mudança no arquivo ou alteração proposta torna a solicitação obsoleta. Auditoria de autor, instante e conteúdo aprovado.

## Por que o patch síncrono não foi consolidado

O primeiro plano reutilizaria `tui_gateway/server_requests.py` e o socket local nativo para entregar a pergunta e aguardar a resposta. O refinamento H1 chegou antes da integração. Esse plano ocuparia o worker durante a espera, perderia persistência e ainda não vincularia o conteúdo completo da alteração.

O rascunho foi preservado em `rascunho-sincrono-nao-integrado.tar.gz` e retirado dos diretórios de produção/testes. É código INCOMPLETO, NÃO EXECUTADO, com chamadas ainda não compatíveis com as APIs atuais. Não extrair como solução nem promover. SHA-256: `234c2155d792a12d9064c0830d6700cb8b1d9a25104a844d206226b705665ea7`.

## Recorte recomendado — uma entrega integrada, etapas sequenciais

1. Govern/CISO: congelar contrato da operação e autoria humana. Identidade composta por board/card/solicitação/origem/perfil/workspace; payload completo, paths canônicos e hashes pré/pós-imagem. Definir qual canal nativo distingue o clique humano de chamada feita por worker/CLI/API. Correlação por request_id sozinha não prova autoria. Fixar o modelo de ameaça: isolamento de superfície vs processo com mesmo UID e acesso ao armazenamento. Não prometer sandbox de SO sem medi-la.
2. Backend: journal transacional da operação + migração aditiva; estado Kanban `waiting_approval`; suspensão controlada liberando claim/slot; decisão humana separada de APIs genéricas de task-update; negação/cancelamento/obsolescência persistentes. Aprovação agenda exatamente uma retomada. Revalidar preimagem, conteúdo, path/symlink e escopo no consumo atômico; não regenerar livremente o patch pelo LLM e não emitir uma segunda pergunta para a mesma operação.
3. Superfície: adaptar `apps/desktop/src/plugins/kanban/{board,drawer,types,api}.ts*` e backend Kanban. Loading/empty/error/forbidden explícitos; diff, contador e uma ação humana. Notificação nativa na origem com confirmação; falha de aviso conserva pedido e bloqueio de escrita. Reabrir deve consultar journal, não memória de socket.
4. Prove/review/release: migração de DB antigo; relógio controlado para espera longa; processo encerrado sem slot ocupado; origem errada, acesso por worker, alteração obsoleta, dupla decisão, duplo consumo e crash na retomada sem escrita indevida. Docker regenerado não-root. Revisão independente. Plano de drenagem sem matar workers; instalação só autorizada após revisão. Prova humana real de aprovação/negação na UI instalada, sem agente clicar por H1.

Estimativa inicial, NÃO medida: 16–32 horas de engenharia/revisão para o recorte integrado; janela de prova humana e implantação à parte. Risco alto: autorização, migração de estado, corrida de retomada e compatibilidade de UI/dispatcher. Não abrir várias frentes antes de congelar o contrato compartilhado.

## Decisão técnica pendente para o orquestrador/CISO

A UX e o escopo já estão aprovados. Falta fixar a autoridade de resposta humana e o recorte estrutural antes de distribuir implementação: o callback síncrono atual recebe apenas os nomes/motivos, não o payload/diff/preimagem que o H1 deve autorizar (`file_tools_write_guards.py:254-339`). O storage `tools/write_approval.py` cobre memory/skills e não substitui esse contrato para AGENTS/SOUL. Alterar somente timeout/transporte/checkbox não satisfaz o requisito.

Recomendação: manter este card como entrega integrada e especificar a etapa 1 com orquestrador+CISO, depois implementar etapas 2–4 no mesmo fluxo ou decompor com contrato único explícito. Não criar cards administrativos nem liberar os dois alvos com base nesta nota.

Uma sonda adicional de resposta JSON-RPC foi bloqueada pelo scanner de comandos antes de executar; não foi repetida por outro caminho. Portanto não há medição de exploração de resposta por transporte estranho e não se afirma vulnerabilidade demonstrada.

## Erguer a régua / Brain

Defeito adjacente observado por leitura: a solicitação protegida atual mostra motivos/nomes, sem conteúdo exato, e aceita choices de escopo como autorização de uma operação. O desenho aprovado exige revalidar hash/diff, não somente melhorar entrega. Absorver esse requisito no recorte já autorizado; sem card adicional. Nenhuma garantia de exclusividade humana ou persistência é declarada como existente.
