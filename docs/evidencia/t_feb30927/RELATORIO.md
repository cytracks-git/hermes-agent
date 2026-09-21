# t_feb30927 — Kanban: tempo e progresso

Writer: executor, gpt-6-astra/openai-codex informado pelo runtime. Sem launchers. Custo financeiro NÃO MEDIDO. RACI: executor implementa; revisor avalia no filho t_af9e17d8; Rel congela o SHA registrado no handoff; PM limita o escopo; CISO acompanha isolamento sem alteração de credenciais; CEO/H1 aceita. Não há autoaprovação.

## Discover / Govern / Act / Prove

WIP de t_c7bee8cc preservado na origem e importado em worktree próprio. Base integrada: 98b44ab166c326ccd84c7c05e24db73a29d46a66, preservando aprovação humana. Nenhum dispatcher, claim ou regra de admissão foi alterado. Motivo preflight_refused.reason é consumido literalmente; contrato conferido em f1f731c1d8e.

Idade, tentativa e heartbeat são leituras separadas. Minutos persistem após hora/dia. Claim ausente não vira primeiro started_at. Heartbeat não é progresso; ausência não vira zero ou arco verde. Fontes navegáveis: run, evento e comentário. Sem ETA, percentuais ou inferência de atividade de modelo/ferramenta. Loading, empty, erro e forbidden têm testes próprios.

## Provas

Docker node:24 com uid/gid do host: red.log reproduz defeitos do WIP; controles.log e controles/ contêm positivos, sabotagens e restauração. Mutante tempo-antigo restaura arredondamento grosseiro. Build regenerado pelo prebuild clean.

UI real: Electron reconstruído e backend real em loopback, com snapshot SQLite obtido por .backup somente-leitura. Sem interceptar respostas e sem chamar modelo. ui-real.log registra textos e foco real; screenshot mostra painel. Backend e cliente isolados foram encerrados. Desktop instalado NÃO foi atualizado; publicação depende de revisão.

Testes e resultados finais constam do handoff e dos logs versionados. Nenhuma alegação de suíte global ou deploy. As tentativas iniciais de E2E por alteração de token foram descartadas: não provaram recusa e um seletor numérico amplo casou texto alheio. Não há alegação de prova de autenticação; forbidden é exercitado como estado de componente nos testes unitários. O negativo final é a perda do claim no snapshot, observado pela UI real. A leitura do drawer tem polling de 30s; o teste aguarda essa cadência, sem acelerar a implementação.

## Reprodução

Na raiz, npm ci --ignore-scripts, node apps/desktop/node_modules/electron/install.js e npm run build --workspace apps/desktop. Docker: node:24, mount da árvore em /repo e dependências Linux em /repo/node_modules, -u "$(id -u):$(id -g)", HOME=/tmp. Em /repo/apps/desktop: ../../node_modules/.bin/vitest run src/lib/time.test.ts src/plugins/kanban; depois LOG_DIR=<diretório> bash controle-negativo-progresso.sh.

UI: criar home descartável com plugins.enabled=[kanban] e kanban.dispatch_in_gateway=false; copiar o board com sqlite3 -readonly <origem> '.backup <destino>'. Iniciar hermes serve --isolated --host 127.0.0.1 --port 9527 com HERMES_HOME e HERMES_KANBAN_DB apontando ao lab e HERMES_DASHBOARD_SESSION_TOKEN aleatório. Em apps/desktop executar ../../node_modules/.bin/playwright test e2e/kanban-live.spec.ts --reporter=list. Informar KANBAN_LIVE_TOKEN_FILE (arquivo privado com token), KANBAN_LIVE_TASK_TITLE (título exato de card real running do snapshot), KANBAN_LIVE_SCREENSHOT e opcional KANBAN_LIVE_URL. Informar também HOME=<repo>/.proof/host-home e HERMES_KANBAN_HOME no backend: HERMES_HOME sob ~/.hermes não isola o registro compartilhado de boards. O spec exige o snapshot em <repo>/.proof/home/kanban.db e KANBAN_LIVE_TASK_ID. Ele usa sandbox Electron existente, pula onboarding pela UI, ativa o plugin pela UI, lê dados reais, navega por Enter, corrompe somente current_run_id no snapshot privado e restaura em finally. Encerrar somente o servidor criado e remover o lab privado; nunca publicar token/DB.

## Resultados finais

Docker não-root: 7 arquivos, 109 testes passaram em 45,54s. Controles: baseline e restaurado 62/62; sete mutantes acusados por asserções; MUTANTES_NAO_DETECTADOS=0. Build limpo rc=0. ESLint: zero erros e duas advertências de document no teste; gitleaks staged rc=0.

E2E real: 1 passed (31.9s). Tentativa 37m19s → 37m20s; foco kanban-event-24528; API leu observedClaim=-1, UI mostrou tentativa desconhecida, restauração recuperou a leitura. SQLite restaurado: t_04ebfaaa|610. PIDs instalados 80370 e 80389 mantiveram início 07:32:23 e 07:32:24; não houve deploy.

## Erguer a régua

Desconhecido não significa parado: backend não publica atividade corrente de modelo/ferramenta nesta superfície. Eventual extensão precisa de contrato próprio; custo NÃO ESTIMADO e risco de falsa telemetria alto. Sem novo card ou implementação adjacente. Hotspot: drawer/board/ui/i18n também contêm aprovação humana; revisão deve comparar contra 98b44ab, não a base antiga do WIP.
