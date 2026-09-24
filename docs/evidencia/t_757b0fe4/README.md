# active_pr: retomada posterior ao PR

## Recorte, decisão e responsabilidade

Card `t_757b0fe4`. Autor: executor Hermes nativo `gpt-6-astra` / `openai-codex`.
Risco alto: alteração de sensor contra trabalho duplicado. Sem chamada paga por token iniciada;
custo financeiro desta sessão indisponível. Sem agente externo por shell.

Base local pedida: `t78-c28-pin`, `587e13cbf9c0fdb1725416dd2cf7f8c5259acbb1`.
Na publicação, o fork ainda tinha `t78-c28-pin=99f4239f1d4fa093251fbdbfe534e4f0dad03c29`.
O commit herdado `587e13cbf9` pertence à frente de claim residual/PR #11; não é autoria deste card.
Hotspot comunicado no board: `hermes_cli/kanban_db_dispatch.py`. Não alterei a reconciliação de claims.

RACI registrado antes da implementação: executor implementa; revisor independente responde
por QA e revisão da guarda (CISO consultado nessa revisão); Rel congela/publica depois da revisão;
PM mantém o recorte; CEO/H1 aceita e decide a janela de restart. Este documento NÃO é aprovação,
freeze, merge, deploy ou aceite humano.

DGAP + Brain: Discover mediu eventos e emissores; Govern decidiu excluir status/reclaimed;
Act alterou somente os eventos elegíveis de active_pr; Prove executou base, corrigido e negativos;
Brain preserva os nomes de teste, receita e limites neste relatório.

## Mudança

A consulta de eventos posteriores ao comentário de PR mais novo passa a aceitar `promoted`
e `unblocked`. O comparador continua `created_at > comentário`, nunca `>=`.
Janela de 24h, guarda de sucesso recente, lane de review, cooldowns, delivery_closed e
validação de assigned permanecem intactos. Nenhuma flag, exclusão de comentário ou fechamento de PR.

`reclaimed` continua fora. `status` também fica fora, por medição, não por simetria:

```text
7|{"status": "triage", "requested_status": "triage"}
6|{"status": "todo", "requested_status": "todo"}
1|{"status": "ready", "requested_status": "ready"}
1|{"completion_contract": "local-only", "from": "https://github.com/cytracks-git/hermes-agent/pull/8", "reason": "Rel recorte overlay local-only"}
```

Consulta em `sqlite3 -readonly ~/.hermes/kanban/boards/atlas/kanban.db`:

```sql
SELECT count(*),payload FROM task_events WHERE kind='status'
GROUP BY payload ORDER BY count(*) DESC;
```

O emissor `plugins/kanban/dashboard/plugin_api.py::_set_status_direct` grava destino efetivo e
solicitado, mas não origem; `kanban_db.py::invalidate_descendants_for_parent_reopen` também emite
status automaticamente. A população medida tem ainda alteração de contrato sem mudança de estado.
A separação confiável de done→ready humano por esse payload é NÃO MEDIDA; status não libera a guarda.

## Prova real read-only, sem operar os cards

Dois processos Docker, código base e corrigido, diretório do board montado `:ro`, conexão
SQLite `mode=ro`, transação de leitura; sem `connect()` do domínio, migrations, claim ou dispatch.
A chamada isolada da guarda foi comparada para todos os cards. Relógio real, sem antecipar a janela.
Saída do board vivo (epoch dos dois processos: 1790236645 / 1790236646):

```text
total 333 333
changed 4
t_0080f67d done active_pr -> None
t_4d735dee ready active_pr -> None
t_c5bacdde ready active_pr -> None
t_e3037b0d ready active_pr -> None
```

Portanto os três ready do corpo passam a liberar. O quarto resultado é esperado:
`t_0080f67d` está done, com comentário de PR em `1790206302` e unblocked em `1790226333`.
A função isolada muda, mas done não é candidato ao dispatcher; não houve respawn.
Nenhum dos outros cards mudou de veredito. A mesma comparação sobre snapshot consistente anterior
(332 cards) produziu exatamente os mesmos quatro deltas; o acréscimo de um card ocorreu entre leituras.
Os JSONs completos de cada leitura estão no pacote de evidências, sem corpos de comentários.

Receita da leitura (executada uma vez com `/work` montado da base e outra do corrigido):

```sh
docker run --rm -i --network none --user "$(id -u):$(id -g)" \
  -v "$HOME/.hermes/kanban/boards/atlas:/board:ro" \
  -v "$ARVORE:/work:ro" -w /work hermes-launch:t_e9aedb24 python - <<'PY'
import sqlite3, time, json
from hermes_cli.kanban_db_dispatch import check_respawn_guard
conn = sqlite3.connect('file:/board/kanban.db?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
conn.execute('BEGIN')
results = []
for row in conn.execute('SELECT id,status FROM tasks ORDER BY id'):
    lane = 'review' if row['status'] == 'review' else 'ready'
    results.append(dict(row) | {'guard': check_respawn_guard(conn, row['id'], lane=lane)})
print(json.dumps({'measured_at': int(time.time()), 'results': results}))
PY
```

## Regeneração, mutante e controles

Ferramenta existente: `scripts/run_tests.sh`; imagem existente com receita em
`docs/evidencia/t_e9aedb24/Dockerfile`. Nenhuma ferramenta nova de prova.
Imagem usada: `sha256:181bda5e9e033de3d451ede9c77ba8ede8defdb9ef526f7ce0d1404028d512d4`.
Linux/Python 3.13.15, pytest 8.3.4. Containers não-root, rede desligada,
fonte read-only copiada para lab descartável. Cada execução remove seu container/lab e a próxima
recria tudo da fonte. Não se recompilou a imagem pois dependências/Dockerfile não mudaram.

Foram acrescentadas duas funções parametrizadas à suíte existente de review:
- retomada por APIs reais (`recompute_ready`, `unblock_task`) + seleção dry-run do dispatcher;
- ordem dos eventos e controles de duplicação. Fixture/mock só em testes isolados:
  existência do perfil, sem executar modelo/worker externo.

A segunda protege PR sem retomada, eventos anteriores/empatados, reclaimed posterior,
status genérico, assigned sem troca ou sem origem/default_assignee; preserva handoffs anteriores.
A primeira também coloca um PR estritamente posterior ao promoted/unblocked: volta a `active_pr`.
Esses casos medem a decisão da guarda e a seleção, NÃO a criação de processo real nem a API GitHub.

Mesmos testes finais, versão antiga contra corrigida:

```text
mutant_rc=1
=== Summary: 1 files, 42 tests passed, 4 failed (100% complete) in 17.6s (1 workers) ===
FAILED test_active_pr_guard_resumes_after_real_requeue[promoted]
FAILED test_active_pr_guard_resumes_after_real_requeue[unblocked]
FAILED test_active_pr_guard_event_order_and_duplicate_controls[promoted-None-1-None]
FAILED test_active_pr_guard_event_order_and_duplicate_controls[unblocked-None-1-None]
restored_rc=0
```

Os quatro falham por `active_pr` onde o contrato exige `None` (não por precondição quebrada).
O corrigido passa 46/46 no arquivo, inclusive os negativos. O mutant usa o código inteiro da base
com apenas o arquivo de testes final copiado para o lab; não altera o checkout de trabalho.

Regressão focal nos cinco arquivos existentes `test_kanban_{db,review_lifecycle,delivery,blocked_sticky,promote}.py`:
protegem cooldown/guardas vizinhas, fechamento, bloqueio sticky, promoção e revisão.
Não foi executada a suíte inteira do Hermes nem toda a área Kanban.
Comparação JUnit por nome completo (listagem em `comparison.txt`):

```text
base {'passed': 96, 'skipped': 1}
new {'passed': 114, 'skipped': 1}
regressions []
removed []
added 18
final_rc=0
real 69.32
user 0.01
sys 0.02
```

O único skip é `test_cross_process_init_lock_uses_windows_byte_range_lock`,
marcado Windows-only nos dois lados. Windows NÃO MEDIDO. `real 69.32` mede fim a fim
Docker + cópia do lab + cinco invocações do runner, não a latência do gateway em produção.

Receita final executada, `$ARVORE` apontando para o worktree e `$EVIDENCIA` para saída:

```sh
/usr/bin/time -p docker run --rm --network none --user "$(id -u):$(id -g)" \
  -v "$ARVORE:/src:ro" -v "$EVIDENCIA:/evidence" hermes-launch:t_e9aedb24 bash -c '
  cp -a /src /tmp/lab; cd /tmp/lab; rm .git; git init -q
  result=0
  for name in db review_lifecycle delivery blocked_sticky promote; do
    bash scripts/run_tests.sh tests/hermes_cli/test_kanban_${name}.py -j 1 \
      --file-retries 0 -- --junitxml=/evidence/new-${name}.xml || result=1
  done
  exit "$result"'
```

A primeira tentativa tinha mount somente leitura no próprio diretório de execução;
o runner passou os testes mas saiu 1 ao gravar `test_durations.json`. Foi descartada e
corrigida pela cópia para lab. Dois casos iniciais usavam precondições incorretas e foram corrigidos
antes do mutante acima. Nenhum desses resultados foi contado como prova verde.

## Estado de entrega e régua seguinte

Implementação e evidência prontas para revisão, sem autoaprovação. Gateway NÃO reiniciado;
nenhuma prova de adoção pelo processo vivo ou spawn real após restart. UI Atlas fora do recorte:
é uma guarda interna do Hermes, não uma feature da interface Atlas.
O restart é janela de H1/Rel; não reaplicar nem re-enfileirar cards por conta desta entrega.

Candidato adjacente por inspeção: `promote_task` emite `promoted_manual`, ainda fora da consulta de active_pr;
a variante de promoção manual não é o `promoted` solicitado por este card. Comportamento em runtime
NÃO MEDIDO neste recorte. Sem correção de carona
nem card novo. Custo estimado de tratar: pequeno (consulta + teste focal); risco médio de ampliar
intenção de retomada indevidamente. Orquestrador decide junto com H1 se abre o recorte.
