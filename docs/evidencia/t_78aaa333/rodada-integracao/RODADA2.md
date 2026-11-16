# t_78aaa333 — recorte de integração 2, congelamento para revisão

## Govern: quem decide e o que foi autorizado

Writer: executor/GPT-6-Astra, openai-codex nativo por assinatura/OAuth. QA/CISO: revisor independente, ainda não executado neste run; nenhuma diversidade de modelo alegada. PM/Rel: orquestrador; H1: único aprovador humano real e Acceptor. RACI registrado antes da execução. Nenhum ask/dev, API paga por token, alteração da instalação compartilhada ou decisão sobre AGENTS/SOUL reais. Custo monetário indisponível.

SDD lido do objeto `origin/main:specops/CYTRACKS-SDD-v4.0-RC.md` no clone autorizado `/Users/farantes/atlas/repos/genesis`: 317 linhas / SHA-1 `8fc4a63af6144b81546f223e2dd5f23c038f5c4c`. Base recebida: `785968cd5b0`, mais o delta preservado de integração. Este relatório sucede `RELATORIO.md`, que permanece como registro histórico, não afirmação da árvore atual.

Recorte autorizado: gesto único, contador, aviso à origem, prova positiva/negativa na mesma árvore e checkpoint versionado. H1 autorizou especificamente recriar o lab `t78-approval-ui` e decidir apenas fixtures descartáveis. Os cliques abaixo NÃO são consentimento H1 nem aceite deste card.

## Act: mudanças da rodada

- Desktop e dashboard web: `Approve once` decide com UM gesto explícito, depois de mostrar diff/conteúdo/hash/origem. Sem checkbox pré-marcado, confirmação extra ou efeito automático ao renderizar. Deny/Cancel permanecem.
- GET `/board` serve `pending_approvals` pelo COUNT de requests `pending`, independentemente do filtro de cards. Desktop e web mostram o número no topo; não fingem zero se um servidor antigo não fornecer o campo.
- TUI adiciona `approval_requested` à lista e ao formatter. Emite aviso nativo `status.update` à sessão assinante, sem enfileirar turno de modelo. Só grava `last_ping_event_id` quando o transporte retorna sucesso; falha rebobina o cursor. O recibo é do transporte, NÃO de leitura humana.
- Testes de API/counter, entrega TUI real via StdioTransport com stream fechado/reaberto, cinco identidades divergentes com retorno à identidade original, e dois processos reais disputando a mesma pré-imagem.
- C35 deixou de ser xfail estrito: a implementação passou e o XPASS foi exposto como falha; agora é teste positivo. Não foi escondido como skip.

Não houve mudança do protocolo de payload nem relaxamento de guarda. Nenhum prazo de expiração humana, alarme automático de 5 minutos, restart ou redispatch foi adicionado.

## Prove: saídas reais e interpretação

Python pelo runner canônico `scripts/run_tests.sh`, Docker com UID 502/GID do operador; host sem instalação de dependências. HERMES_HOME/DB/workspace das fixtures isolados. JS em container Node com `npm ci --ignore-scripts`, não prova de permissão de E/S. Não somar suites sobrepostas como testes únicos.

### Integração e regressão

`rodada2-integracao-concorrente.log` / `.rc`:

    Summary: 5 files, 51 tests passed, 0 failed ... in 36.7s
    rc=0

Inclui approve/deny/cancel, pré-imagem/symlink/ilegível, capacidade global/perfil, recuperação de órfãs, identidade profile/session/run/claim/task recusada sem consumir grant, restauração da identidade original com escrita positiva, e concorrência de DOIS workers reais (um verified/applied_at; outro acusa pré-imagem alterada). API não autenticada/hash errado/replay recusados.

`rodada2-comuns-final.log`, mesmos 80 alvos do harness existente:

    Summary: 80 files, 605 tests passed, 0 failed, 4 skipped ... in 19.5s
    rc=0

Os skips são explícitos do runner; há testes Windows que não rodam no Linux. A comparação baseline/candidato anterior, preservada em `baseline-comuns.*`/`candidato-comuns.*`, precede esta rodada. NÃO declarar que a baseline foi refeita aqui. O teste C35 passou de xfail para positivo, logo o denominador/resultado mudou legitimamente.

### Controle negativo / versão velha

`rodada2-mutantes-exec.log` / `.rc`, harness existente:

    BASE (sem sabotagem): rc=0 falhas=0
    N12 revalidação removida: rc=1 falhas=4 -> ACUSOU
    ...
    RESTAURADO: rc=0 falhas=0
    TODAS as 12 sabotagens foram acusadas, com rc real do runner canonico.

As 12 mutações rodaram sobre a mesma produção exercitada pela UI. Depois só foram acrescentadas as medições de identidade/concorrência ao teste. Não chamar essas 12 mutações de cobertura total de todos os defeitos possíveis.

`rodada2-notif-antigo.log`: módulo TUI de `785968cd5b0`, restante da árvore/teste atual. Falha comportamental, não erro de importação:

    test_approval_notice_retries_failed_transport_without_waking_model
    assert len(frames) == 1
    E assert 0 == 1
    1 failed, 14 deselected
    rc=1

Candidato: mesmo teste passa na suite de 51. Stream fechado não gera recibo, não decide a request e não acorda modelo; stream novo recebe o frame com sessão/request corretas, registra recibo e não repete no próximo poll. Sessão errada não recebe o evento. Não é prova de aviso recebido no Desktop instalado ou por H1.

### UI e build

    rodada2-ui-unit.log: 36 passed (36), 6.43s, rc=0
    rodada2-tsc.rc: 0
    rodada2-web-build.log: built in 2.71s, rc=0

O teste de UI verifica ausência de POST antes do clique e exatamente um POST depois dele, vinculado ao hash mostrado; resposta 403 não oferece decisão. Testes unitários não substituem os exercícios abaixo.

### Interface real regenerada: positivo e negativo

Lab novo `t78-approval-ui`, não-root, home/banco/workspaces descartáveis. FastAPI/dashboard/plugin reais, lifespan desligado para NÃO iniciar provedores/gateway/dispatcher de produção. Bundle web reconstruído. Browser em `http://127.0.0.1:18783/kanban`. Dependência ausente `uvicorn` foi instalada somente no lab em `/tmp/lab/deps` (0.35.0; click 8.5.0, h11 0.16.0). Isso não altera dependências do produto. <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->

1. Worker real da fixture, reutilizado de `tests/tools/test_file_approval_worker.py::_worker`, propôs `old\n` → `approved\n`. Drawer mostrou diff/hashes/caminho/run. Um clique em Approve once: `Written and verified.`, estado `consumed`, drawer `running`; eventos atualizados sem reabrir o drawer. Clique → estado visível medido em **2,539 s**, incluindo polling/renderização/CDP. Não é latência pura do worker, SLA nem benchmark.
2. Outra fixture propôs patch em AGENTS.md E other.txt. Recarreguei a página: a request continuava pending e ambos os diffs voltaram do banco. Um clique Deny: `multi_patch · denied`, drawer `blocked`, contador `Pending approvals: 0`. Clique → estado visível **0,521 s**.
3. Conferência externa no container em `rodada2-ui-external.log`:

    positivo: consumed, applied_at preenchido, run_id=current_run_id=1,
              created_by_pid=worker_pid=2837, same_claim=1
    positivo/AGENTS.md b'approved\n'
    sha256=7f8518f7db5e9a55049f49c4ea6d6e8f509695231e60cbd607bcb36c88a75a14
    negativo: denied, applied_at=null, status=blocked
    negativo/AGENTS.md b'old\n'
    negativo/other.txt b'old\n'
    erro real: BLOCKED: Approval denied; no write performed
    uid=502

Não se tocou em pedido verdadeiro do board Atlas. Desktop Electron instalado, entrega à origem H1 e resposta H1 continuam NÃO MEDIDOS (C28/C29); dependem de revisão, plano de rollout/drenagem e consentimento fresco. Não destravar AGENTS/SOUL com estes cliques de teste.

## Falhas de preparação preservadas, não vendidas como execução

- `rodada2-mutantes.log`: caminho de saída `/saida` indisponível, antes das mutações.
- `rodada2-mutantes-final.log`: cópia Python seguiu symlinks do venv macOS e falhou antes das mutações. Corrigido com preservação de symlinks; runner usou Python do container, não o venv quebrado. Artefato de execução verdadeiro é `rodada2-mutantes-exec.log`.
- A cópia de testes inicialmente levou `.git` apontando ao worktree do Mac; runner imprimiu erro de precompilação Git, mas executou e reportou as suites. A regeneração final deve usar objeto Git arquivado, sem `.git`, `.venv`, node_modules do host ou caches; nunca copiar ambiente macOS para Linux como dependência.
- Primeira suite comum acusou XPASS estrito C35. Retirada exclusivamente a marca xfail, seguida de suite completa positiva (`comuns-final`).
- Primeiro servidor UI não iniciou por ausência de uvicorn na imagem antiga. Health check acusou HTTP000; corrigida dependência no lab, health check HTTP200, só então cliques.

Essas falhas não são mutantes sobreviventes, regressões do produto nem justificativa para alterar guardas. Nenhuma nova recusa de scanner foi reapresentada por outra rota; o teste de UI usou a autorização específica posterior de H1.

## Prontidão para produção: inventário, não promessa

| Exigência | Existente / prova | Lacuna antes de recomendar rollout |
|---|---|---|
| Espera humana versus técnica | pending/granted/consumed e waiting_approval persistidos; UI explicita approved aguardando worker/capacidade; tests capacidade positiva/negativa | granted ainda mistura lock/capacidade/retomada; não há diagnóstico contextual detalhado de motivo/idade/última evidência/próxima ação |
| Entrega rastreável | evento/request e cursor/last_ping; TUI falha/retoma medidos; gateway usa notificador existente | recibo não exposto no painel; falha técnica TUI sem limite próprio/configuração/contador durável; confirmação de transporte não prova leitura |
| Progresso útil por etapa | requested/granted/resumed/denied/orphaned e recibo applied_at; recuperação real sem replay medida | painel não correlaciona ausência de avanço com operação em voo/erro repetido; heartbeat só prova vida |
| Limites e custo | teto ativo desconta espera; polling cresce de 0,1 até 2 s; não há turno LLM nessa espera | polling e tentativas técnicas não configuráveis; consumo real de CPU/I/O durante espera longa NÃO MEDIDO; custo monetário indisponível |
| Recuperação única | consumo CAS; preimagem; run/PID/claim; duas aplicações concorrentes; órfã nos três estados; reabertura da UI | restart completo do servidor entre grant e consume, falha parcial de filesystem e UI de órfã/erro técnico ainda sem exercício ponta a ponta nesta rodada |

Há risco de espera técnica prolongada em produção. NÃO recomendar rollout como protegido contra esse risco com base nestas provas. H1 corrigiu explicitamente a proposta de 5 minutos: relógio isolado NÃO caracteriza defeito. Nenhum cron/alarme periódico foi implementado.

Próxima decisão material, no MESMO card: definir diagnóstico contextual usando os eventos/notificador/dispatcher existentes, com motivo/última transição/última evidência/ação em voo e contagem de erro repetido sem ganho. Avisar/corrigir só por desvio material, sem matar trabalho válido, redispatch, expirar decisão humana ou aprovar sozinho. Estimativa de planejamento e integração após decisão: 2–4 h, NÃO medida; risco médio pela persistência/concor­rência. Nenhum card filho criado por demora.

## Limites de contrato que precisam de decisão explícita

- O payload v3 é autorização de bytes `post_blob`, sem semântica por alvo para exclusão/rename. O compilador atual falha fechado em V4A Move/Delete e alvos remotos; não fabrica arquivo vazio nem fallback. Isto NÃO é apresentado como cobertura desses modos. O recorte AGENTS/SOUL write/Update foi medido. H1/arquiteto/revisor precisam confirmar esse recorte ou aprovar ampliação do contrato antes de implementar rename/delete/transporte remoto. Não resolver mudando o contrato silenciosamente.
- C17 foi ampliado com teste de profile/session/run/claim/task divergente; C31 agora também exercita o aplicador real com dois workers, além da fixture arquitetural. Não afirmar que isso substitui a matriz inteira de falhas de filesystem ou restart.
- Segurança de fronteira contra agente com acesso ao mesmo usuário/credenciais do humano NÃO foi demonstrada; a revisão CISO deve avaliar o principal autenticado e a separação de credenciais antes de instalar.

## Freeze / revisão / lição de preparação

Congelar o delta desta rodada e o herdado em commit revisável, junto com evidências; revisão por `revisor`, nunca autoaprovação. Instalação, publicação e aceite H1 permanecem zero. Nenhum arquivo protegido real foi reemitido.

Lição reutilizável para preparar os próximos recortes: antes de iniciar, resolver fonte canônica + permissões autorizadas + árvore portátil + runner/dependências do container + critérios do recorte + dependências humanas + aceite + orçamento. Registrar o primeiro resultado útil e preservar chamadas/checkpoint; atualização nova precisa de evidência material, não passagem do relógio. Ao falhar preparação, corrigir apenas a causa diagnosticada no mesmo card, sem abrir nova frente ou repetir Discover. Essa orientação fica versionada aqui, não em wrapper/global de outro perfil.

Erguer a régua: os riscos reais acima bloqueiam recomendação de rollout; custo de fechamento depende da decisão de contrato/observabilidade, não de adicionar mais um harness. Não criei ferramenta de prova nova nem card adjacente. A varredura de evidências com gitleaks retornou `no leaks found`; recibo final do commit/limpeza será anexado na transição do Kanban.
