# C28 — o que a janela de rollout mediu, incluindo o que deu errado

Rodada 1137. Escrito durante a espera, com as saidas reais coladas dos arquivos
irmaos desta pasta. Nada aqui e inferido de leitura de codigo: e o que os
instrumentos `harness/*.sh` imprimiram nos dois lados da janela.

## 1. A pausa segura funcionou, e foi medida

Restricao H1 (1139): pausar a atividade viva, nao matar, retomar do checkpoint.

Instrumentos criados para NAO chutar o momento:
- `harness/janela-segura.sh` — porteiro com codigo de saida (0 abre, 1 fecha,
  2 nao-medido). Tres condicoes medidas: sessao desktop com mensagem recente,
  `active_agents`/`gateway_busy` do backend, turno em voo (ultimo papel=user).
- `harness/inventario-atividade.sh` — separa ATINGIDO (app + backend `serve` +
  sessoes que ele hospeda) de PRESERVADO (gateway e worker do card, ambos ppid=1).
- `harness/checkpoint-atividade.sh` — IDs + marca d'agua (msgs, ultimo ts) antes
  e depois, para conferir por CONTEUDO e nao por "o app abriu".

Controle do porteiro (nao e enfeite: ele mudou de veredito nos dois sentidos):
- 22:42 com janela de 5min -> FECHADA (sessao 20260920_164003_9511e3 falando)
- 22:42 com janela de 600min -> FECHADA (controle positivo: 4 sessoes)
- 22:46 com janela de 5min -> ABERTA
O porteiro tambem foi corrigido em voo: a primeira versao acusou 4 "turnos em
voo" de 19/09 — turnos ABANDONADOS, nao em voo. Sem recencia, um porteiro que
nunca abre e tao inutil quanto um que nunca fecha.

Pausa executada 22:47:58 por `osascript -e 'tell application "Hermes" to quit'`
— gesto de menu, NAO sinal. Readback 22:48:24:
- 56897 (app) e 56920 (backend serve): AUSENTES, como esperado
- 78236 (gateway) e 98991 (este worker): VIVOS
Nenhum sinal foi enviado a processo algum nesta pausa. Sem SIGKILL, sem SIGTERM.

## 2. Defeito A — o app REABRE sozinho e fica orfao da propria arvore

Medido, nao suposto:
- quit confirmado 22:48:24 (pids ausentes)
- 22:48:42 nasce `Hermes.app` pid 6990, **ppid=1**, tag launchd
  `application.com.nousresearch.hermes.396376432.396377616`. Eu nao o iniciei.
- 22:48:53 o pack comeca (staging `.staging-6899-1789955333`)
- o swap renomeia `release/mac-arm64` -> `.previous` e apaga o `.previous`

Resultado medido com lsof no pid 6990:

    Hermes 6990 txt REG ... /apps/desktop/release/mac-arm64.previous/Hermes.app/Contents/MacOS/Hermes
    Hermes 6990  16r REG ... /apps/desktop/release/mac-arm64.previous/Hermes.app/Contents/Resources/app.asar

E o diretorio nao existe mais:

    ls: .../release/mac-arm64.previous: No such file or directory

Ou seja: um app rodando codigo que foi deletado do disco no meio do pack. Um
`ps` ingenuo veria "Hermes.app vivo" e chamaria de sucesso — e exatamente o
falso-verde que a regra 11 proibe. So o lsof mostra que o inode carregado nao e
o do bundle novo (409941117 no disco vs 396377616 carregado).

Licao para o proximo rollout: **conferir o INODE/caminho que o processo carregou,
nunca o nome do processo.** `harness/snapshot-desktop.sh` ja imprime pid+lstart;
falta imprimir o caminho do asar via lsof — corrigir antes da proxima janela.

## 3. Defeito B — o rebuild foi revertido por um `hermes update` que eu nao iniciei

Sequencia medida:
- 22:49:16 meu rebuild termina. Bundle novo com o painel: `waiting_approval=1`
  em `app.asar.unpacked/dist/assets/index-L9Y3U83l.js`, stamp
  `contentHash=0ea1024e...`, instalacao em HEAD=643ffa7a82c (commit do card).
- 22:51:45 relanco o app pela via suportada (`hermes desktop --skip-build`).
- 22:52:02 nasce `scripts/desktop-update/posix.sh --daemonized ... --desktop-pid 10133`
  (pid 10511, ppid=1) e as 22:52:11 dispara
  `hermes update --yes --gateway --keep-stash --branch main`.
  **Nao fui eu.** E o auto-update do proprio Desktop, acionado pelo relancamento.
- o update leva a instalacao de 643ffa7a82c (card) para main = eaef5ec7178,
  autostash `hermes-update-autostash-20260921-015324`, e REBUILDA o desktop a
  partir do main.

Estado depois (`snapshot-depois-update.txt`), medido:

    instalacao: eaef5ec7178  (main — sem os commits do card)
    app.asar.unpacked/dist: marcador waiting_approval=0 arquivo(s)
    stamp contentHash=a35f9bd1...  builtAt=2026-09-21T01:54:59Z

O painel saiu do bundle. **C28 nao esta entregue.** Dizer o contrario porque o
app esta aberto seria mentira: o bundle vivo nao tem o codigo do card.

Causa raiz, e ela ja estava escrita no card (commit 82606b2d56f, "orfao entre
worktree e instalacao"): o codigo do C28 vive so no branch
`executor/kanban-aprovacao-interativa`. A instalacao compartilhada estava
DETACHED nesse commit; qualquer `hermes update --branch main` a puxa de volta
para main e leva o rebuild junto. Rebuild em cima de instalacao detached e
reversivel por um update que nem sou eu quem chama.

## 4. Defeito C — o gateway completa o teardown e nao morre; o update espera 30min por um PID que nao vai sair

`~/.hermes/logs/gateway.log`, 22:55:10, teardown INTEIRO em 0.14s:

    Shutdown phase: drain done at +0.01s (drain took 0.00s, timed_out=False,
      active_at_start=0, active_now=0, cron_at_start=0, cron_now=0, ...)
    Gateway stopped (total teardown 0.14s)
    Gateway housekeeping stopped

E as 23:03, oito minutos depois, o processo 78236 continua vivo (STAT=S), com
threads paradas em `PyThread_acquire_lock_timed`. Nenhum trabalho ativo: o
proprio log diz active=0 em todas as categorias.

Enquanto isso `~/.hermes/logs/update.log` repete a cada 30s:

    ⏳ still draining — 1361s left before the forced restart
       (gateway did not report what it is waiting on — pre-update gateway or unreadable state file)

Essa segunda linha e FALSA, e da para provar em uma leitura. O arquivo de estado
esta perfeitamente legivel:

    $ jq -r '{gateway_state, active_agents, active_work, exit_reason}' ~/.hermes/gateway_state.json
    { "gateway_state": "stopped", "active_agents": 0,
      "active_work": null, "exit_reason": "Gateway restart requested" }

O motivo de `active_work` ser null nao e "gateway pre-update" nem "arquivo
ilegivel": `gateway/run.py:3965` so preenche `active_work` quando
`gateway_state == "draining"`. Aqui o estado e `stopped` — o gateway ja terminou
o teardown. `hermes_cli/update_cmd_drain_report.py:85-86` colapsa os tres casos
(campo ausente, gateway velho, arquivo ilegivel) numa frase so, e escolhe a
explicacao errada. O operador le "gateway velho" e vai procurar problema onde
nao tem.

A frase honesta seria: *"o gateway publicou state=stopped sem trabalho ativo, mas
o processo 78236 continua vivo — o teardown terminou e a saida travou"*. Isso
aponta para o defeito de verdade (processo que nao sai) em vez de inventar um
arquivo ilegivel.

Nao corrigi B nem C nesta run, de proposito: o card manda implementar no
worktree e nao editar a instalacao compartilhada antes de revisao, e nenhum dos
dois e o escopo C28. Ficam como achado com prova, para o orquestrador rotear.

## 5. O que sobreviveu (retomada conferida por conteudo, nao por PID)

O `checkpoint-atividade.sh` rodou nos dois lados e o `diff` dos dois arquivos e
a prova — tres linhas de diferenca, todas explicadas:

    20c20
    < 20260920_164003_9511e3|60|1789954788|Otimizar skills, agents
    > 20260920_164003_9511e3|68|1789956892|Otimizar skills, agents
    24d23
    < 584|t_f4d1c062|4356

- a sessao 9511e3 GANHOU 8 mensagens (60 -> 68): o operador seguiu conversando
  durante a janela. Nao perdeu nada; avancou.
- a run 584 saiu da lista de abertas porque TERMINOU sozinha: consultada no
  banco, `ended_at=22:54:26 outcome=completed`, card t_f4d1c062 agora `done`.
  Concluiu, nao foi morta. Ela nasceu as 22:44 e atravessou a janela inteira.
- as outras 14 sessoes abertas: contagens identicas nos dois lados.
- worker deste card (98991): vivo o tempo todo, nunca foi alvo.
- worktree `executor/kanban-aprovacao-interativa`: intacto; os 10 commits do
  card seguem alcancaveis pelo branch mesmo com a instalacao de volta em main
  (`git rev-list --count eaef5ec7178..executor/kanban-aprovacao-interativa` = 10).
- cron: 0 jobs ativos ANTES; 8 DEPOIS (default 7, executor 1). Nao foi o rollout
  que os criou — o gateway novo (pid 15290) recarregou os jobs que ja existiam
  no disco; o gateway velho havia sido iniciado antes deles. Nada foi retomado
  em duplicata por mim: eu nao iniciei job algum.

Nenhuma atividade util foi morta nesta janela. O que quebrou foi o proprio
rollout, por um update automatico — nao o trabalho do operador.

## 6. Fim da espera: o update terminou pela via suportada

23:13:32–23:13:59, sem intervencao minha: `✓ Service restart requested`,
`✓ Restarted ai.hermes.gateway`, gateway novo pid 15290 @ eaef5ec7, servindo os
5 perfis, dispatcher do Kanban de volta. O drain de 30min nao chegou ao fim —
o updater desistiu da espera e reiniciou, como projetado. Total de espera
observada: ~18min de mensagens falsas sobre "arquivo ilegivel".

Eu nao matei o gateway travado. Ele foi substituido pelo proprio fluxo do
updater.

## 7. Por que C28 PARA aqui, e nao "quase la"

Para colocar o painel no bundle vivo eu precisaria: rebuild + fechar/reabrir o
Hermes.app. Medido as 23:19 e 23:23, o porteiro fecha a janela:

    20260920_041002_636708 ult=23:22:15
    20260920_164003_9511e3 ult=23:22:55
    VEREDITO: JANELA FECHADA — esperar ponto seguro

O operador voltou a trabalhar nas duas sessoes do Desktop. A restricao do H1 e
explicita: aguardar ponto seguro, nunca matar trabalho util. Fechar o app agora
derruba a interface de quem esta usando.

E mesmo com a janela aberta, repetir o mesmo gesto daria o mesmo resultado: a
instalacao volta para main no proximo relancamento, porque o poller de update do
Desktop (`apps/desktop/src/store/updates.ts`, `startUpdatePoller`) dispara a
atualizacao apontada para main sempre que o app sobe. Rebuild em cima de
instalacao detached nao sobrevive ao proprio relancamento que o valida.

As duas saidas possiveis sao decisao de quem manda, nao minha:
  (a) apontar a instalacao para o BRANCH do card (nao detached) durante a
      janela, para que um update na mesma branch nao desfaca o rebuild; ou
  (b) suspender o auto-update do Desktop durante o rollout e religar depois.

Ambas mexem em configuracao da instalacao compartilhada, que este card proibe
sem revisao. Por isso: bloqueio com prova, nao "entrega parcial".

