# PR #14 — vermelhos corrigidos, revisão pendente

Roteamento: executor nativo gpt-6-astra/openai-codex. RACI antes da implementação: executor R código/provas; revisor A revisão/QA, C segurança; Rel A freeze depois de CI/revisão; PM escopo do card; H1 aceite. Sem wrappers, label ci-reviewed, merge ou mudança de configuração viva. Custo financeiro indisponível; rota nativa de assinatura.

## Discover / Govern

Head inicial 1e595ff0e595039141930ae1e49423ff840747eb; base real do PR 587e13cbf9c0fdb1725416dd2cf7f8c5259acbb1. Risco alto: leitura de configuração alimenta o sensor de rota. Escopo: config-read guard, botocore e flake do dock. Não enfraquecer guardas/baselines e não criar ferramenta paralela.

## Act

- Substituído YAML direto por load_user_config_effective(path, fail_closed=True), API oficial sem defaults inventados, com overlay gerenciado, cache e expansão de env. Leitura de outro perfil instala e restaura seu secret scope, evitando herança acidental do lançador.
- Chave do agrupamento de cota considera rotas efetivas; apenas mtime do config.yaml perderia mudanças em .env/política gerenciada. Parse permanece cacheado pelo loader oficial.
- Dois testes novos: A→B→A em multiplex com env do lançador divergente e controles de rota aposentada/saudável; invalidação de agrupamento após mudar só .env ou overlay. Ambos matam a implementação antiga.
- CI inclui --extra bedrock, estático, nas duas instalações de tests.yml. Botocore ausente foi reproduzido na base: não era defeito do preflight. Nenhum lock/dependência foi repinado; extra existente passou a ser instalado antes da suite.
- Flake do dock: avisos de inicialização do shell em chunks separados encerravam a limpeza no primeiro chunk vazio e poluíam a atividade. A limpeza agora continua até o primeiro payload; saída posterior permanece intacta. Teste determinístico isolado falha no antigo; dois controles positivos garantem preservação do payload e de texto semelhante após payload. Os testes existentes mantêm processos reais e stop real; não substituímos E2E por mock.

## Prove

Logs integrais junto do relatório. Containers regenerados --rm, rede desativada e -u "$(id -u):$(id -g)". Imagem local hermes-launch:t_e9aedb24, Python 3.13.15, acrescida de boto3==1.42.89 botocore==1.42.89 jmespath==1.1.0 s3transfer==0.16.0; para regressão de processos, ptyprocess==0.7.0. Dependências instaladas como root na imagem, testes não-root. CI remoto usa uv sync --locked/Python 3.11: ambiente local não é alegado equivalente.

Receita: montar worktree em /work e Git comum read-only no caminho original; bash scripts/run_tests.sh tests/hermes_cli/test_config_read_guard.py tests/hermes_cli/test_kanban_route_preflight.py tests/hermes_cli/test_kanban_route_preflight_dispatch.py tests/hermes_cli/test_kanban_shared_quota_dispatch.py tests/hermes_cli/test_process_dock.py tests/agent/test_bedrock_adapter.py --file-retries 0.

Saída em três execuções: 121 tests passed, 0 failed, respectivamente 6.5s, 3.6s e 6.6s. No head antigo, mesmos testes novos: 20 passed, 3 failed em 8.4s (env/overlay/dock). O teste antigo de dock não falhou nos replays locais ordinários; a reprodução determinística mata especificamente o chunk que antes produzia 'last: bash: no job control in this shell' em vez de 'starting'. Não alegamos diagnóstico único de todos os possíveis flakes.

Regressão focal adicional justificada pelo arquivo de processos tocado: bash scripts/run_tests.sh tests/tools/test_process_registry.py tests/tools/test_process_registry_list_exit.py --file-retries 0 → 117 passed, 0 failed, 4 skipped, 16.4s. A primeira execução teve 6 falhas por ptyprocess ausente na imagem local; imagem corrigida antes da repetição. Os quatro skips são originais da suite, não adicionados.

Justificativa de provas: configuração efetiva altera fronteira entre perfis e sensor de rota, logo controles positivo/negativo e mutante. Dock muda leitor compartilhado, logo payload preservado e regressão focal. Não mede login/provider real, quota financeira, egress, UI atlas.local ou deploy. Sensor de config passou sem allowlist nova; guardas de processos intactos. Erro de ownership Git na precompilação best-effort local não foi escondido; testes realmente executaram.

## Brain / erguer a régua

Somente estatísticas de YAML não invalidam configuração efetiva; teste preserva esse contrato. Defeito adjacente não tratado: limpeza de shell baseada em chunks ainda merece avaliação de fragmentação dentro de uma mesma linha (não medida aqui; custo estimado baixo/médio, risco de ocultar payload). Não criar frente extra nem declarar corrigida. Runtime local SQLite emite aviso de WAL-reset e usa DELETE; atualizar imagem é melhoria separada. CI exato, revisão e freeze ainda pendentes neste relatório pré-push; resultados posteriores vão ao card/PR.
