# t_78aaa333 — retomada 550: freeze limpo e plano de prontidão

## Govern — envelope e decisão pendente

Este é o retrabalho administrativo pedido em 1067/1068, não uma aprovação do produto. Writer: executor / GPT-6-Astra / openai-codex nativo. QA/CISO: outro agente pelo perfil revisor. PM/Release: orquestrador. H1: decisão de risco residual, resposta à operação protegida e aceite. Nenhum agente preenche decisão em nome de H1.

Base recebida: `13fae88d749c753e7f89e837484fdb984dd78d0a`; produção/testes: `351bfa47b3c367727192cedac4a38180fdbd96ad`. R1/run549 permanece diagnóstico atribuído ao revisor, NÃO revisão elegível retroativamente. Seu impedimento foi árvore suja desde o início. Não se reescreveu esse run.

SDD lido de objetos `origin/main` no clone autorizado `/Users/farantes/atlas/repos/genesis`: 317 linhas, SHA1 `8fc4a63af6144b81546f223e2dd5f23c038f5c4c`; registro `sdd-rules.json` lido. Referências históricas a wrappers não se sobrepõem à proibição atual H1. Sem wrapper, API de inferência adicional, edição de instalação/perfil ou alteração de AGENTS/SOUL reais.

Recorte desta rodada: remover os três resíduos identificados, revalidar o código congelado em árvore regenerada, discriminar controles existentes de cenários faltantes e entregar proposta fechada de diagnóstico/rollout para decisão. Não implementar uma alteração estrutural de observabilidade antes do plano combinado exigido em 1057/1058. A feature integrada permanece parcial quanto à prontidão instalada.

## Discover/Act — resíduos classificados e removidos

Autorização posterior à recusa de limpeza: comentário1067, por caminhos exatos e pelo autor. Cada remoção foi chamada separada sujeita ao scanner; nenhuma nova recusa ocorreu.

| Resíduo | Identidade / classificação | Destino |
|---|---|---|
| `.t78-frozen.tar` | 198 MiB por `du -sh`; SHA256 `2775673cdf149c156e5bc400e2ea80f01791b8ef692dcbbe955c15c49241eed4`; mesmo arquivo registrado em FREEZE.md, regenerável com git archive do commit351bfa47b3c | removido |
| `.t78-old-notifications.py` | 44 KiB por `du -sh`; SHA256 `55c1d4354c638270471aa0f83e8adff0d230e8e44e1a1647caaf04ae43fe58f8`, idêntico a `785968cd5b0:tui_gateway/session_notifications.py`; cópia da versão antiga para comparação | removido |
| `.t78-web-dist/` | 3,2 MiB por `du -sh`; assets/fonts/index.html de build descartável; NÃO evidência única, receita e recibos de build/UI já versionados | removido |

`gitleaks dir` sobre a cópia antiga e o bundle antes da remoção: `scanned ~42284 bytes ... no leaks found`; `scanned ~2289733 bytes ... no leaks found`. O archive foi identificado pelo hash do freeze, não houve alegação de scan binário integral. Nenhum resíduo foi movido para outra pasta a fim de esconder sujeira; nenhum git clean, exclusão global ou alteração de ignore.

Depois das três remoções: `git status --porcelain=v1` vazio e `git diff --exit-code 13fae88d749 --` RC0. Isto é o início limpo das medições abaixo, NÃO sana o início do run549.

## Prove — regeneração e controles nesta rodada

Container novo `t78-r550-proof`, rede `none`, fonte do host somente-leitura, nenhum volume de dados nem credencial. Imagem já existente e inspecionada `atlas-prova-t78:harness`, ID `sha256:ab45d35b943737c7d5065f7459a6596a69fc041e32723d2c2563034022d62ce8`. Dependências pertencem à imagem; não se alega imagem reconstruída nesta rodada.

Fonte extraída diretamente de `git archive 13fae88d749` para `/tmp/work` dentro do container. Nada de `.venv`, node_modules ou `.git` do host. `id` devolveu:

    uid=502 gid=20(dialout) groups=20(dialout)

Runner canônico, `HERMES_PYTHON=/usr/local/bin/python3`, `HERMES_TEST_FILE_RETRIES=0`. Lista versionada `alvos.txt`; harness já existente `../harness/prova.sh` (a partir da pasta pai t_78aaa333). Recibo durável em `revalidacao.log/.rc/.ids`:

    rotulo=revalidacao rc=0 falhas=0
    Summary: 4 files, 72 tests passed, 0 failed (100% complete) in 37.7s

Primeira execução dos mesmos quatro arquivos: 72/0 em38,9s, saída no transcript deste run. Não somar as duas execuções nem confundir estimativa `~46` do coletor com o total real72 (parametrização). Nenhum teste de E/S foi silenciosamente aprovado como root. A etapa auxiliar de bytecode imprime `fatal: not a git repository`, pois o archive não contém `.git`; o runner executa os testes e seu RC é capturado separadamente, não pelo último comando de um pipe.

### O que os cenários realmente medem

| Contexto | Caminho existente executado | Resultado e limite |
|---|---|---|
| Espera humana | `test_kanban_approval_wait.py`: relógio controlado, cinco varreduras, teto ativo descontado; worker real cria pending | persistência/slot medidos; não equivale a dias reais de consumo de memória |
| Capacidade global/perfil ocupada | `test_file_approval_worker.py::test_real_worker_waits_and_writes_only_the_approved_preimage[capacity_host/capacity_profile-*]` | granted continua waiting, bytes old; liberar competidor permite verified, mesmo PID/claim; não mede motivo contextual exibido |
| Erro técnico de pré-imagem/symlink/E/S | mesma bateria, estímulos preimage/symlink/unreadable | BLOCKED, sem aplicação autorizada; unreadable executado uid502; não prova toda falha parcial de filesystem |
| Aviso com transporte fechado | `test_approval_notice_retries_failed_transport_without_waking_model` | falha mantém pending/sem recibo; novo stream recebe frame de sessão/request exatas; segundo poll não duplica; NÃO existe painel de diagnóstico durável de erro neste teste |
| Worker morto | `test_dead_creator_is_recovered_without_replaying` nos três estados | orphaned/blocked, segunda reconciliação vazia; não prova restart de todo serve/gateway instalado |
| Fronteira de API | `test_kanban_file_approval_api.py` | auth/hash/identidade do corpo/replay recusados; NÃO sandbox contra processo hostil de mesmo UID |

Controles negativos de entrada e positivos são pareados dentro da mesma bateria: deny/cancel/preimagem/ilegibilidade versus approve/capacidade liberada. Nada foi inserido no board vivo.

Controle de regressão adicional, MESMO teste de transporte e MESMA árvore, apenas o módulo `tui_gateway/session_notifications.py` substituído no container pelo objeto antigo785968cd5b0:

    notifier-antigo.rc: 1
    assert len(frames) == 1
    E assert 0 == 1
    1 failed, 14 deselected

Não é erro de import/compilação. Restaurado o arquivo candidato da própria cópia antes da mutação:

    notifier-restaurado.rc: 0

Logs completos adjacentes. Não reexecutei os12 mutantes do freeze nem80 arquivos comuns: nada de produção/testes mudou nesta rodada, e repetir a revisão total não é o recorte pedido. Não houve exercício novo de browser nem build nesta rodada; as provas UI anteriores continuam limitadas ao lab.

## Govern — proposta cirúrgica de diagnóstico contextual (1057/1058)

Estado atual é insuficiente para recomendar produção protegida contra demoras técnicas. O retorno `None` em `tools/file_approval_worker.py::apply_granted` colapsa lock do dispatcher, orçamento global/board/memória e capacidade por perfil. `_wait` não registra esse motivo. No notificador TUI, falha de entrega rebobina cursor; quando o transporte apenas retorna falso não há recibo durável do motivo/tentativas. `approval_api.py` lista o journal; não serve diagnóstico adicional. Isto é leitura de caminhos aliada aos cenários executados acima, não prova de detector que ainda não existe.

Proposta para decisão, NÃO código instalado nem contrato aceito:

1. Estender os eventos atuais, sem novo daemon, cron ou tabela de autorização. Evento `approval_progress` vinculado a task/run/request e etapa, contendo `reason_code`, `expected_next`, `evidence_event_id` e `attempt`. Emitir somente ao mudar etapa/motivo/evidência; não a cada poll nem pela idade. Nenhum payload de conteúdo/segredo nesse evento. Preservar os estados/consumo do journal.
2. Tornar o resultado da admissão existente explicável no produtor: `dispatcher_lock`, `board_capacity`, `host_capacity`, `profile_capacity`, `memory_pressure`. A decisão e o motivo devem vir da MESMA avaliação sob o lock existente; não recalcular heurística no frontend. Alteração de interface interna e consumidores exige revisão antes de patch.
3. Projeção no GET existente do drawer, separada do payload imutável: `phase`, `reason`, `last_transition_at`, `last_evidence_at`, `next_action`, `delivery_status`, `delivery_attempts`, `resource_cost`. `pending` significa Human decision pending; `granted` sem observação de admissão significa Resume reason not yet observed, NÃO Capacity full por palpite; consumed sem recibo significa Application outcome not yet confirmed. Timestamp é informação, nunca gatilho de falha. CPU/I/O sem medição aparece Unavailable, não zero.
4. Rastreamento do aviso em eventos existentes por request+assinatura+geração do transporte. Recibo significa Transport acknowledged, nunca Human read. Proposta de limite configurável `kanban.approval_notice_max_attempts=3` por geração/conexão, como configuração registrada com leitor/teste, NÃO nova env var. Esgotamento preserva pedido e mostra Delivery failed; só reconexão real ou ação humana Retry notice abre outro orçamento, sem redespachar a escrita. Número3 é proposta a decidir, não limite medido ou vigente. Não criar alerta repetitivo nem inferir defeito de uma pausa sem log.
5. Desvio contextual: erro técnico confirmado ou repetição do mesmo erro sem nova evidência → uma atualização com motivo/ação. Em caso de transporte indisponível, o board conserva o erro; só anunciar aviso entregue quando o transporte saudável acusar recibo. Trabalho útil em voo e espera humana/capacidade não viram incidente. Nenhum kill/restart/reclaim/autoapprove por esse diagnóstico.

Plano de teste restrito da proposta (faltante, NÃO confundir com a tabela anterior): estender os testes existentes worker/notifier/API/UI, sem novo harness. Exigir (a) capacidade ocupada e lock ocupado produzem motivos diferentes com os mesmos bytes intactos; (b) relógio avançado com pending não cria erro/alerta; (c) falha real de stream mostra erro/tentativas e a reconexão recebe uma atualização correlacionada; (d) repeated poll sem mudança não cria novos eventos/avisos; (e) aplicação segue única depois da recuperação; (f) UI loading/empty/error/forbidden e próxima ação em inglês; (g) recurso de espera medido em processo real não-root, com duração/amostragem declaradas. Só esses exercícios podem fechar o diagnóstico, não a suíte72/0 desta rodada.

Estimativa não medida: 2–4h de implementação+prova após decisão, no MESMO card; risco médio de concorrência/volume de eventos. Zero nova plataforma/card/harness. Alternativa de manter o código como está significa manter rollout bloqueado, não declarar risco aceito. Decisão material pendente: representação e limite de tentativa acima. Revisão deve avaliar esse plano em vez de exigir ferramenta de prova inédita.

## Govern — plano de rollout, drenagem e reversão

### Portões e responsabilidades

1. Revisor inicia NOVA sessão com HEAD e porcelain limpos, termina com o mesmo HEAD/porcelain, e emite parecer técnico de código congelado+plano. Não usar `kanban_complete` para representar aprovação somente técnica: liberaria os filhos antes de prova instalada. Defeito concreto → `kanban_request_changes`; risco/decisão externa efetivamente faltante → registrar parecer técnico e `kanban_block(kind='needs_input')`, para o orquestrador coordenar neste card. Não repetir a revisão toda só porque H1 ainda não clicou.
2. CISO avalia alcance concreto same-user: a API recusa credencial de serviço, mas aceita principal de sessão local (`local-session-owner`) ou sessão autenticada. NÃO provado que um worker do mesmo UID não possa alcançar credencial/DB/arquivo. Não ler/extrair segredo real para demonstrar isso. Decisão residual pertence a H1; a frase histórica do contrato§1.4 que toma alternativa(a) por padrão NÃO constitui aceite e NÃO autoriza rollout. Se a exigência for resistência a processo hostil do mesmo UID, é necessária autoridade/sandbox externa ao UID — mudança estrutural, não um novo booleano nesta guarda.
3. Resolver o recorte contextual acima e revisar seu delta; C28/C29 e aviso à origem H1 continuam pendentes. Consentimento geral1064 é delegação de escopo, não clique humano. Não reemitir operação real antes do consentimento fresco suportado.

### Preparação não disruptiva (somente após parecer técnico elegível)

PM/Rel inventaria pela infraestrutura nativa de update/status o checkout que serve, SHA carregado por processo, processo/supervisor/pid+fingerprint, perfis atendidos e localização do bundle Desktop/web efetivo. Usar `hermes update --plan` para inventário, NÃO `hermes update` como instalação cega deste branch. A origem configurada do upstream pode não conter o patch do fork. Nenhum comando de instalação foi executado nesta rodada.

Fixar no mesmo recibo: SHA anterior, SHA candidato revisado, componentes Python+plugin+Desktop/web, dependências, baseline de tests, versões servidas e origem da conversa do card. Escolher operação nativa de promoção do SHA exato somente depois de conhecido o supervisor/instalação; não improvisar cherry-pick/reset na instalação compartilhada em uso. A revisão libera elegibilidade técnica, não o ato disruptivo.

Snapshots consistentes por mecanismo nativo de backup, incluindo todos os perfis/DBs alcançados e suas assinaturas de aviso; nunca `cp` isolado de DB SQLite vivo omitindo WAL. Não copiar secrets para docs/anexos. Confirmar que a restauração é recuperável antes da janela; não testar restore sobre o DB vivo.

### Drenagem e cutover condicionado

PM/Rel obtém autorização da janela/disrupção exigida pelo corpo e identifica mecanismo suportado de suspender NOVAS admissões, mantendo os workers atuais vivos. Não usar SQL/CLI alternativo para contornar propriedade do card. Drenagem é observação de trabalho ativo por run/PID/fingerprint/etapa, não relógio. Se a opção de restart puder matar processo ao expirar prazo, NÃO usá-la com trabalho em voo; parar o plano antes de enviar sinal.

Requests waiting_approval são processos vivos e precisam entrar no inventário, mesmo sem slot/claim. Não aguardar conclusão do próprio H1 para sempre numa janela nem encerrar esses workers automaticamente: a presença deles exige adiar janela ou decisão pontual do H1. Guardar checkpoints e deixar chamadas terminarem. Os filhos AGENTS/SOUL permanecem gated.

Após a drenagem comprovada, promover o SHA/bundles revisados pelo mecanismo elegível, iniciar/recarregar só os componentes inventariados e conferir SHA EFETIVO nos processos novos, não só no disco. Verificar migração aditiva do journal, integridade, contagens de tasks/runs/requests antes/depois, subscriptions, contador e acesso auth. Sem prova de versão servida ou se algum processo continuar carregando versão antiga: abortar o avanço para pedidos reais.

### Prova instalada exigida para fecho

C28: operador abre Desktop instalado na origem correta, vê coluna/contador/diff/hash/request/task/run; reabre UI e pedido persiste. Conferir aviso entregue à conversa original com identidade/sessão corretas. Não basta status do notificador ou capture do lab.

C29: operação verdadeira, limitada e com consentimento fresco; H1 faz o único gesto no mecanismo suportado. Agente NÃO usa browser/GUI/API para decidir. Conferir bytes/hashes reais, consumed/applied_at, mesmo run/PID/claim e apenas uma aplicação; registrar tempos pedido→aviso, clique→retomada separados da espera humana/capacidade. Não executar publicação AGENTS nem propagação SOUL como parte da correção: alvos continuam sendo trabalho dos respectivos cards após o portão.

Negativos reais controlados continuam em fixture/lab: deny, aviso indisponível, origem/perfil errado, perda de UI, capacidade ocupada, worker morto, replay e restart. Resultado nenhum desses autoriza escrever arquivo protegido real ou fabricar decided_by. Se a prova real não puder acontecer com H1 ausente, conservar prontidão parcial e registrar pendência — nunca simular aceite.

### Reversão

Defeito após instalação: suspender novas admissões pelo mecanismo autorizado, preservar processos/chamadas/checkpoints e journal. Voltar código/bundles ao SHA anterior somente após drenagem e readback. Não apagar a tabela nem reverter decisões; downgrade deixa waiting_approval sem despacho no código antigo (contrato M-4). Com request pendente/consumida, reversão automática de DB ou replay é proibido: precisa inspeção de payload+bytes e decisão humana antes de nova operação. Backup é recuperação de desastre, não permissão para perder eventos posteriores.

Rel mede após rollback: SHA efetivo Python+UI, processo/fingerprint, integridade do board, pedidos e arquivos intactos ou aplicação já registrada, nenhum replay/novo worker inesperado. Só então encerra janela. Se restauração não for comprovada, permanece bloqueado; não declarar rollback seguro por desenho.

## Brain — escopo de entrega e régua

DGAP desta retomada: Discover=causa administrativa e lacunas identificadas; Govern=proposta limitada com portões; Act=limpeza exata e regeneração; Prove=72/0 e controle antigo/restaurado; Brain=receita e distinção explícita entre código, diagnóstico e instalação. Não houve alteração de UI nesta rodada; estados Datadog exigidos para a proposta não são vendidos como entregues.

Fronteiras ainda NÃO MEDIDAS: C28/C29 instalados, origem real H1, resistência same-user, consumo CPU/I/O da espera longa, diagnóstico contextual implementado e reversão instalada. Custo financeiro indisponível; nenhum token/API adicional de inferência. Aviso do lab: SQLite3.46.1 usa journal_mode=DELETE pela proteção nativa contra WAL-reset; não alterar runtime global para esconder esse aviso. Risco/custo de atualização da imagem fica registrado, sem novo card e sem nova frente.

Preparação para a próxima sessão: iniciar em commit/porcelain limpos; gerar fonte portátil por objeto Git dentro do container (sem arquivo temporário no host); usar o runner existente e capturar RC real; decidir o recorte estrutural pendente antes do patch. Revisão anterior com início sujo continua inválida, mesmo depois da limpeza. Recibos/hash do commit/push e teardown devem constar na transição deste run.

## Recibo de restauração e teardown

SHA256 iguais entre container restaurado e worktree:

    tui_gateway/session_notifications.py
    dfc05f3f0762c3925f7ad9f6359e4112822b3cb9ef84a5c13bf03a0aeee124e4
    tools/file_approval_worker.py
    b1db84678212afbff0bf07b44b64dbd22689091cca73cb3e8167fcc8b3490a24
    hermes_cli/kanban_db_approvals.py
    96252f15324f4659f0a79fdef8eeb5c6c62476411a00c3b8564d4a60258bf194

`git diff --exit-code 13fae88d749 -- tools hermes_cli plugins apps tui_gateway gateway tests`: RC0; o delta deste run é exclusivamente documentação/evidências. `gitleaks dir` sobre esta pasta: `scanned ~28184 bytes ... no leaks found`, RC0 (antes deste apêndice; varredura staged final consta da transição).

Em `2026-09-20T20:12:59Z`: `docker stop t78-r550-proof` e `docker rm t78-r550-proof` concluíram. Readback por nome exato em `docker ps -a` vazio. As três asserções `test ! -e` passaram, saída `residuos_herdados=0`. Vetor declarado: esse container, seus processos/arquivos efêmeros, nenhum volume/rede/porta nova e os três temporários herdados; containers/serviços alheios preservados. Não se declara resíduo zero de toda a máquina.
