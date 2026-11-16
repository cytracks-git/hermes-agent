# Prova de suite — card t_78aaa333 (aprovação humana persistente)

Registro do que foi medido, como, e com qual resultado. Escrito depois de o H1
recusar o ciclo anterior por três vícios de método; cada um vira uma precondição
fixa aqui.

## As três precondições (impostas pelo H1, 2026-09-20)

1. **RC real, nunca o de um `tail`.** O ciclo anterior rodava
   `pytest | grep | tail`, e o `exit_code` lido era o do `tail` — verde
   fabricado. `harness/prova.sh` redireciona a saída para arquivo e captura
   `$?` na linha seguinte; não há pipe na cadeia inteira (`docker run` →
   `prova.sh` → `run_tests.sh`).
2. **Runner canônico, nunca `pytest` cru.** `AGENTS.md` exige
   `scripts/run_tests.sh`: ele impõe paridade com a CI (credenciais
   desativadas, `TZ=UTC`, `HERMES_HOME` temporário) e **isola cada arquivo em
   subprocesso próprio**.
3. **Alvos idênticos dos dois lados.** O ciclo anterior comparou listas
   diferentes e chamou a diferença de "pré-existente" — isso não é controle.
   `harness/alvos-comuns.txt` é a única fonte da lista para baseline e
   candidato, e `prova.sh` **recusa rodar** (`exit 2`) se qualquer alvo faltar
   na árvore. Arquivo de teste novo não entra na comparação: vai para
   `alvos-novos.txt` e é reportado à parte.

## O que a precondição 2 revelou

Rodar bare `pytest` com todas as suítes num processo só produziu **24 falhas**.
As mesmas suítes pelo runner canônico: **604 passaram, 0 falharam**.

As 24 falhas eram **contaminação entre arquivos de teste** — dicts de módulo e
`ContextVar` vazando entre suítes que o runner isola por subprocesso. Eram
artefato do método, não defeito do código. É exatamente o incidente que o
`AGENTS.md` documenta ("works locally, fails in CI" e o inverso) e a razão de o
runner existir.

Consequência de método: **a comparação com baseline ficou dispensável para essas
24** — sem falha nenhuma no candidato, não há o que caracterizar como novo ou
pré-existente. O baseline continua necessário se alguma falha aparecer.

## Medições (todas no container, regra 12)

Imagem: `harness/Dockerfile`, sobre `kanban-body-t5a6:proof` (pytest 8.3.4),
mais `fastapi==0.133.1` / `starlette==0.52.1` para a suíte do dashboard.
`HERMES_PYTHON` aponta para o python do container — é o caminho que o próprio
`run_tests.sh` prevê quando não há venv local, não um contorno.

| Rodada | Comando | Alvos | RC real | Resultado |
|---|---|---|---|---|
| Candidato, alvos comuns | `harness/candidato.sh` | 80 arquivos | **0** | 604 passaram, 0 falharam, 4 skipped |
| Candidato, alvos novos | `harness/candidato-novos.sh` | 1 arquivo | **0** | 28 passaram, 0 falharam |
| Controle negativo | `harness/negativo.sh` | 11 sabotagens | **0** | 11/11 acusadas |

Os 4 `skipped` são testes `windows_only`, que rodam na lane `tests-os`.

## Controle negativo (regra 6)

Cada guarda é sabotada isoladamente numa cópia gravável; a suíte que deveria
protegê-la tem de ficar vermelha, com RC real. Sabotagem que passa em verde é
defeito do teste, e o script termina com RC != 0.

| # | Sabotagem | Acusou |
|---|---|---|
| N1 | pause mantém o claim (espera ocupa vaga do orçamento) | sim (1) |
| N2 | resume não restaura identidade no mesmo CAS | sim (3) |
| N3 | pause encerra o run (habilitaria o reaper a matar quem espera) | sim (15) |
| N4 | `enforce_max_runtime` deixa de descontar a espera humana | sim (1) |
| N5 | unicidade de pendência deixa de ser UNIQUE | sim (1) |
| N6 | varredura de órfãs ignora `consumed` não-aplicada | sim (1) |
| N7 | E-8 camada 1: cláusula de origem some do UPDATE | sim (1) |
| N8 | E-8 camada 2: `_apply_status` não olha a origem | sim (2) |
| N9 | entrada em `waiting_approval` por verbo genérico volta a ser aceita | sim (1) |
| N10 | um verbo genérico passa a LEVAR para `waiting_approval` | sim (1) |
| N11 | coluna `waiting_approval` some do board | sim (4) |

### Três defeitos que o controle negativo encontrou (e que foram corrigidos)

1. **`ApprovalPendingExists` nunca dispararia.** A detecção casava o nome do
   índice parcial na mensagem do SQLite, que nomeia apenas **colunas**
   (`UNIQUE constraint failed: approval_requests.task_id, ...`). Uma segunda
   pendência vazaria `sqlite3.IntegrityError` cru para o chamador. Trocado por
   consulta ao banco (`pending_for_run`), que pergunta o fato em vez de ler
   string.
2. **A camada 1 de E-8 não era medida.** Todos os testes entravam pela camada 2,
   então apagar a cláusula do UPDATE passava em verde (N7 era exatamente esse
   falso verde). A camada 2 lê o status e só depois chama o handler — tem janela
   TOCTOU; **a camada 1 está dentro do txn e é a que garante**. Teste dedicado
   (`test_layer_one_guard_holds_when_the_pause_races_the_drag`) chama o handler
   direto, simulando a pausa que cai entre a leitura e a escrita.
3. **A recusa de entrada mentia.** Tentar `PATCH status=waiting_approval` caía
   no fallback "unknown status" — falso, porque o estado É válido; ele só não é
   um destino alcançável pela UI. Mensagem própria
   (`_WAITING_APPROVAL_DESTINATION_MSG`), e o teste passou a proibir o texto
   genérico.

## O que estas medições NÃO provam

- **Não há prova de UI.** Nada foi exercitado no `atlas.local` pelo fluxo do
  operador (regra 12-A). A coluna `waiting_approval` foi medida na API do
  dashboard, não na tela.
- **A etapa 4 não existe** (guards de escrita em `tools/` + endpoint de
  decisão). Sem ela não há feature de ponta a ponta: o journal e o estado estão
  de pé, mas nada ainda os aciona a partir de uma escrita real de worker.
- **Nenhuma feature e nenhuma coluna estão entregues.**

## Reproduzir

```sh
cd docs/evidencia/t_78aaa333/harness
docker build -t atlas-prova-t78:harness .
sh candidato.sh        /tmp/prova-t78   # suítes comuns <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
sh candidato-novos.sh  /tmp/prova-t78   # suítes novas <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
sh negativo.sh         /tmp/prova-t78   # controle negativo <!-- no-tmp: ok — recibo historico do lab; apagar /tmp falsificaria a prova -->
```

Cada rodada grava `<rotulo>.log`, `<rotulo>.rc` (RC real) e `<rotulo>.ids`
(ids de falha, um por linha) no diretório de saída.
