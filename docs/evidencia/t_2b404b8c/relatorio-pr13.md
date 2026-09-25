# PR #13 — correção de CI, sem dispensa de gate

Roteamento: executor nativo gpt-6-astra/openai-codex. RACI antes da implementação: executor R código/prova; revisor A revisão/QA e C segurança; Rel A freeze após CI/revisão; PM escopo literal do card; H1 aceite. Sem wrappers, sem label ci-reviewed e sem merge. Custo financeiro indisponível; somente rota de assinatura configurada.

## Discover / Govern

Head inicial daa55c088bc5075dfb97f7680b93ef2e839e0818; base real do PR 587e13cbf9c0fdb1725416dd2cf7f8c5259acbb1. Escopo: vermelhos de scratch, LSP e dependência de testes; nenhum lab/configuração viva do operador modificado. Risco médio: cleanup de teste e dependências; fronteira de admissão não mudou.

## Act

- Prova SQLite usa get_scratch_dir(), não literal de diretório temporário.
- Referência documental passa a apontar aos três arquivos já versionados. Nenhuma inclusão na baseline do sensor de scratch.
- LSP: o finally não sinaliza zumbi já morto/reparentado; preserva cleanup de filho vivo e lida com NoSuchProcess. Não há bypass do guarda, skip ou retry acrescentado.
- CI instala extra bedrock do lock existente nas duas instalações do workflow tests.yml. Mudança estática, sem interpolação de dados externos. Base e head também falhavam sem botocore; o caso não era defeito de Kanban.

## Prove

Saídas integrais junto deste relatório. Docker Linux, usuário numérico não-root do host, rede desativada nos testes, containers novos --rm. Imagem local usada: hermes-launch:t_e9aedb24 (Python 3.13.15), acrescida de boto3==1.42.89, botocore==1.42.89, jmespath==1.1.0 e s3transfer==0.16.0; depois ptyprocess==0.7.0 para regressão do outro PR. Instalação root só da imagem, nunca execução dos testes. O CI remoto usa Python 3.11 e uv sync --locked; não alegamos paridade total com a imagem local.

Receita focal: montar este worktree em /work e o diretório Git comum somente leitura no caminho original; executar bash scripts/run_tests.sh tests/agent/lsp/test_client_e2e.py tests/scripts/test_check_no_tmp_literals.py tests/hermes_cli/test_kanban_corpo_comprimido.py tests/agent/test_bedrock_adapter.py --file-retries 0.

Saída: 4 files, 146 tests passed, 0 failed, 20.7s. LSP corrigido passou três execuções sem retry e sem --init (a primeira integra o focal). Antes: LSP passou três execuções com --init tanto na base quanto no head, mas ambos falharam sem reaper no finally, por os.kill fora da subárvore. Mesmo estímulo no corrigido passou: mutante/controle negativo preservado nos logs. O guarda permanece intacto.

Prova existente regenerada: montar em /w e HERMES_HOME=/w/.proof-home; python docs/evidencia/t_00542312/prova_fronteira.py depois. SQLite recusou corpo truncado, com zero linhas; corpo íntegro 5967 caracteres passou byte a byte; comentário íntegro passou e comentário truncado foi recusado. O sensor de scratch antes acusou o literal documental remanescente; depois passou sem exceção nova.

Justificativa: foco nos vermelhos e regressão da fronteira cuja receita de prova mudou. Não mede egress, auth real, produção, atlas.local nem aceite humano; não são alvo deste card de CI Hermes. A imagem local emite aviso de SQLite 3.46.1 vulnerável ao WAL-reset e ativa DELETE; melhoria adjacente: atualizar imagem de prova, custo baixo/risco de reprodutibilidade, não executada como nova frente. Erro de ownership Git só afeta precompilação best-effort; o scanner de árvore e os testes executaram.

## Brain / próxima ação

Comparar base e head sob o mesmo reaper separou flake de regressão; instalar extra do lock remove dependência de instalação durante o teste. Revisão e freeze continuam pendentes. O resultado do CI do SHA publicado será registrado no card/PR, sem inventar aprovação neste relatório anterior ao push.
