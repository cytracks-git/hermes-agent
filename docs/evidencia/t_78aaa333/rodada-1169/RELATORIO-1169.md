# Rodada 1169/594 — freeze da reconciliação com main

Card: t_78aaa333 · Writer desta run: executor / grok-4.6 / xai-oauth
Produção congelada: `66a8c213bbb647cceda63e7d66efe0daa4eed739`
(`reconcilia main eaef5ec7178 na branch do card`)

Este commit de evidência, se existir depois, é só recibo. Não muda produção.

## Recorte desta run

Fechar o candidato reconciliado e mandar a revisão. C28 (GREEN visível no
Desktop) e C29 (gesto humano) continuam FORA. Instalação compartilhada
`~/.hermes/hermes-agent` = `main` @ `eaef5ec7178`, porcelain vazio — não tocada.
Nenhum dispatch, nenhum `--dry-run`, nenhum swap/restart.

Filhos inspecionados e permanecem gated: t_5924c6bc (AGENTS, blocked),
t_af463e6a (SOUL, triage), t_d9d95368 (G1, todo). Completar este pai os
liberaria sem C28 — não completei.

## Discover — o que a reconciliação preservou

Conflito real era um: `tui_gateway/session_notifications.py`. Medido agora no
HEAD congelado, as duas mudanças convivem:

- `_KANBAN_NOTIFY_KINDS` contém `approval_requested` (linha 136)
- `_BOT_DELIVERY_POLL_SECONDS` existe e é usado (linhas 139 e 778)

`git diff --name-only eaef5ec7178..66a8c213` no código (sem `docs/`): 35
arquivos do card. Main não foi rebobinada.

## Prove — Docker uid 502, `--network none`, imagem `atlas-prova-t78:harness`

Readback do container: `uid=502 gid=20(dialout)`. Imagem
`sha256:ab45d35b943737c7d5065f7459a6596a69fc041e32723d2c2563034022d62ce8`.
Árvore de prova = `git archive HEAD` em scratch, nunca o worktree.

    recorte 1057/1058   6 arquivos    87 testes    0 falhas   rc=0   41.1s
    comuns (regressão) 80 arquivos   623 testes    0 falhas   5 skip rc=0   28.3s
    negativo 1057      10 sabotagens 10 ACUSARAM   base rc=0, restaurado rc=0   77s

Recorte e comuns: logs `recorte-1169.log` / `comuns-1169.log` (rc em arquivo,
não em pipe), corridos contra HEAD 66a8c213 às 00:22. Negativo: regenerado
nesta run (01:11–01:12) pelo harness já versionado
`harness/negativo-docker.sh` + `controle_negativo_1057.py`. Controle positivo:
base e restaurado verdes — o sensor não acusa sempre.

M7 (diagnóstico acordaria o modelo) sabotou exatamente a linha do merge
(`approval_requested` em `_KANBAN_NOTIFY_KINDS`) e foi acusada. Portanto a
resolução do conflito não cegou a guarda.

## O que isto NÃO prova

- C28: operador vendo coluna/contador/request no Desktop da origem. NAO MEDIDO
  nesta run. O bundle instalado continua o da main (auto-update da rodada 1137).
- C29: clique humano real. Não simulado.
- Comportamento instalado / rollout. A instalação compartilhada não mudou.
- Entrega visível do prompt protegido para AGENTS/SOUL. Continua o bloqueio
  original dos filhos.

## Erguer a régua (sem card novo, R<1)

- Incidente 1162: `hermes kanban dispatch --dry-run` reapou worker vivo.
  Já no thread. Não reexecutei.
- `main-preservada-docker.sh` nasceu untracked nesta árvore; não entrei no
  commit (ferramenta nova = escopo novo).
- `.prova-run589/` é cópia inteira de repo; não entra no git.
- Revisor desta entrega: perfil `revisor`. Writer e orquestrador nesta
  família (xai/grok-4.6) — declarado, não fingido. Independência = outro
  perfil/sessão, não outra família.

Custo financeiro: indisponível. Só OAuth/assinatura.
