# t_78aaa333 — checkpoint de integração, ainda não aceito

## Govern / freeze

Roteamento: executor, GPT-6-Astra via openai-codex, execução nativa. RACI: Writer=executor; QA/CISO=reviewer independente; PM/Release=orquestrador; decisão humana e aceite=H1. Não houve outro agente, wrapper ask/dev, chamada de modelo por API paga, deploy ou alteração do runtime instalado. Custo monetário: indisponível.

A norma foi lida do objeto Git canônico em `/Users/farantes/atlas/repos/genesis`: 317 linhas, SHA-1 `8fc4a63af6144b81546f223e2dd5f23c038f5c4c`.

Base desta rodada: `785968cd5b0`, branch `executor/kanban-aprovacao-interativa`. Alterações permanecem no worktree, SEM commit novo. Não há aprovação do autor, revisão externa ou aceite do H1. Não promover este checkpoint como entrega concluída.

## Act — o que existe no caminho real

- `tools/file_tools.py`: write_file e patch de worker proprietário entram na aprovação persistente; chamadas fora desse caso mantêm o caminho anterior.
- `tools/file_approval_payload.py`: compila bytes/diffs antes da espera, usa o parser V4A existente sobre buffer, persiste pré/pós-imagem, recusa aliases e revalida resolução/hash. Lock de arquivo entre processos além do lock local.
- `tools/file_approval_worker.py`: cria request e pausa na mesma transação; espera decisão persistida; preserva identidade/fingerprint nativo do dispatcher; respeita capacidade global e por perfil; consome uma vez; verifica bytes escritos e retoma o mesmo run/claim/PID. Faz staging antes de alterações multifile e rollback para falhas recuperáveis. Crash de SO não é transação de filesystem e não autoriza replay.
- `hermes_cli/kanban_db_approvals.py`: trigger de imutabilidade da identidade e payload.
- `hermes_cli/kanban_db.py`: CAS de retomada inclui current_run_id; composição transacional explícita nos métodos de espera.
- `hermes_cli/kanban_approval_lifecycle.py` e dispatcher: decisão vinculada ao hash, negação/cancelamento e recuperação de órfãs pending/granted/consumed; não reexecuta escrita.
- `plugins/kanban/dashboard/approval_api.py`: endpoints específicos do pedido, autenticação da sessão do dashboard, recusa credencial de serviço, não aceita identidade enviada no body. Não há ferramenta de modelo nova nem verbo genérico de aprovação.
- Desktop e dashboard web: painel com payload/diff completos, hashes, origem, aprovar uma vez com confirmação, negar, cancelar, erros e estados persistidos.
- Notificação usa o evento realmente emitido, `approval_requested`, sem acordar modelo para decidir. O teste Python novo exercita o evento persistido, não uma string presumida.

## Prove — saídas reais

Execução Python sempre por `scripts/run_tests.sh`, dentro de containers novos, com `-u "$(id -u):$(id -g)"`. HERMES_HOME e bancos das fixtures são temporários. `HERMES_TEST_FILE_RETRIES=0`. Nenhuma decisão dos testes se refere ao card real ou aos arquivos de instrução do operador.

### Baseline e candidato: mesmos 80 arquivos

Lista: `../harness/alvos-comuns.txt`. Harness: `../harness/prova.sh`. Baseline foi regenerada com `git archive HEAD`; candidato foi copiado do worktree para diretório temporário do container. RC capturado pelo harness, não pelo último estágio de pipe.

    baseline-comuns: rc=0
    Summary: 80 files, 604 tests passed, 0 failed, 4 skipped ... in 33.1s
    candidato-comuns: rc=0
    Summary: 80 files, 604 tests passed, 0 failed, 4 skipped ... in 22.8s
    same_failed_ids=True

Não tratar diferença de duração como benchmark de desempenho. Os skips são reportados nos logs. Esta comparação precedeu os últimos ajustes de notificação/UI; não é um selo de árvore final inteira.

### Integração selecionada final

    final-integracao: rc=0
    Summary: 3 files, 25 tests passed, 0 failed ... in 34.4s

Alvos: `tests/tools/test_file_approval_worker.py`, `tests/plugins/test_kanban_file_approval_api.py`, `tests/gateway/test_kanban_notice_copy.py`.

Inclui processos separados e SQLite real: approve/deny/cancel, pré-imagem alterada, troca por symlink, arquivo ilegível sob UID não-root, patch multifile, comentário não autorizador, hash incorreto, payload imutável, decisão repetida, consumo único, mesma identidade na retomada, capacidade global e por perfil ocupada/liberada, órfãs nos três estados sem replay. API: sem autenticação recusado, body não pode escolher identidade, replay/hash incorreto recusados. Não se afirma que isso cobre toda a matriz adversarial do contrato v3.

### Frontend

    ui-unit-final: rc=0
    Tests 36 passed (36)
    typecheck-final: rc=0
    web build: rc=0, built in 7.12s

Alvos unitários: approval-panel, completion-notify e drawer do Desktop. São testes unitários de UI com transporte de teste, não prova de um humano real. O bundle web foi construído pelo build normal; seu painel IIFE é servido como módulo separado. Último ajuste de atualização do drawer web (descrito abaixo) tem somente verificação sintática nesta rodada.

### Controle negativo e mutante

Harness existente ampliado com N12, removendo somente a revalidação imediatamente antes da escrita. Mesma suite no candidato e no mutante:

    BASE: rc=0 falhas=0
    N12: rc=1 falhas=4 -> ACUSOU
      preimage-patch
      preimage-write
      symlink-patch
      symlink-write
    RESTAURADO: rc=0 falhas=0
    TODAS as 12 sabotagens foram acusadas, com rc real do runner canonico.

Logs individuais e manifestos do harness estão nesta pasta. Mutação executada antes dos últimos ajustes de recuperação de erro/notificação/UI; não confundir com repetição sobre um commit final (inexistente).

### Interface real — controle positivo isolado

Lab Docker `t78-approval-ui`, UID não-root, HOME/banco/workspace próprios, app FastAPI e dashboard real; sem lifespan para não iniciar gateway/dispatcher/provedores reais. Browser em `http://127.0.0.1:18783/kanban`. Arquivo-alvo exclusivamente `/lab/positive/AGENTS.md` com conteúdo de fixture.

O drawer exibiu o pedido/diff/hash. A automação clicou `Approve once` e `Confirm approval` SOMENTE nesta fixture. Não é aprovação do H1, nem aceite deste card.

Conferência independente no container (`ui-positivo.log`):

    {"state":"consumed","applied_at":1789930060,"created_by_pid":18,
     "run_id":1,"status":"running","current_run_id":1,"worker_pid":18,"same_claim":1}
    bytes=b'approved\n'
    sha256=7f8518f7db5e9a55049f49c4ea6d6e8f509695231e60cbd607bcb36c88a75a14

UI passou a mostrar `Written and verified.`. Tempo clique→retomada não foi isoladamente medido; a espera incluiu inspeção manual do DOM.

## Bloqueio efetivo e o que NÃO foi provado

O comando composto que copiaria o JS atualizado ao lab e iniciaria a fixture negativa multifile foi recusado ANTES de executar:

    BLOCKED: Security scan — [HIGH] Nested executable body could not be resolved
    nested command analysis was incomplete ... bounded nested-shell depth,
    lexical-candidate, input, or retained-body budget

Não foi reapresentado por wrapper, encoding ou outro caminho. A prova negativa pela INTERFACE ficou pendente; os controles negativos via testes de integração acima efetivamente rodaram.

Um uso posterior de execute_code, exclusivamente para sanitizar tokens de fixture em log, também foi recusado globalmente em single-query (`tool_calls_made=0`). Não foi usado outro executor para repetir essa transformação; o log bruto sensível foi simplesmente excluído, e o restante passou no gitleaks.

Pendências concretas antes de revisão/aceite:

1. Autorizar/definir a execução limitada da fixture negativa de UI sem transpor a recusa do scanner; reconstruir o lab e repetir positivo+negativo sobre o estado final.
2. Verificar vivo o último ajuste web: na primeira prova, o painel via polling mostrou `consumed`, mas o status/eventos do drawer continuaram antigos sem o canal WS operacional. Código agora pede refresh do card/board ao mudar o estado persistido; somente sintaxe foi verificada após esse ajuste. Não declarar esse defeito resolvido por leitura.
3. Fechar a matriz restante do contrato v3 (incluindo tentativas cruzadas de identidade/run/perfil, consumidor concorrente e UI de erro/órfã), sem substituir essas medições pela lista parcial acima.
4. Validar recorte de patch: esta implementação recusa operações V4A Move/Delete em pedido protegido; não está demonstrado que esse limite satisfaça o contrato. Alvos remotos também falham fechado, sem fallback.
5. Revisão independente via `kanban_request_review(reviewer='revisor')` somente após implementação/provas terminadas. Nenhum deploy antes disso.

## Limpeza / segurança das evidências

Primeiro gitleaks encontrou 29 ocorrências no log bruto HTTP do lab: tokens efêmeros de sessão em URLs. O log foi removido, sem imprimir tokens em chat. O relatório diagnóstico preservado já é redigido (`--redact`). Segunda varredura:

    scanned ~132510 bytes ... no leaks found
    rc=0

O arquivo temporário `checkpoint.tar` usado para regenerar baseline foi removido. O container de UI foi removido; nenhum worker real ou container alheio foi encerrado. Logs das suites e código permanecem neste worktree.

Erguer a régua: refresh assíncrono do drawer é defeito observado, com ajuste ainda não provado ao vivo; fechar essa medição e a negativa de UI é próxima ação limitada, estimativa 20–40 min, risco médio por envolver autenticação e aplicação de arquivo. Demais faltas do contrato acima impedem aceite e não foram transformadas em cards novos. Nenhuma frente adjacente foi iniciada.
