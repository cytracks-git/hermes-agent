# Bateria de mutantes — t_e9aedb24 (fronteira de identidade no lançamento)

Runner canônico `scripts/run_tests.sh` dentro de `hermes-launch:t_e9aedb24`, com
`docker run -u "$(id -u):$(id -g)"` — medido `uid=502 gid=20(dialout)`, NÃO-root:
nenhum teste aprova por CAP_DAC_OVERRIDE.

Regra aplicada: mutação que não altera o `shasum -a 256` do arquivo é ERRO DE
HARNESS, nunca "mutante morto". Os quatro sha abaixo foram medidos, e todos
divergem do original — os mutantes foram de fato aplicados.

## Tabela

| # | Defeito reintroduzido | Arquivo | sha256 sob mutação | Resultado | Quem acusou |
|---|---|---|---|---|---|
| M1 | Aviso removido da origem do lançamento Desktop (`cmd_gui`) | `hermes_cli/main_desktop.py` | `c26eb5ef4629…9a8b1a` | MORTO (4✓ 1✗) | `test_launch_restriction_notice.py::test_desktop_launch_warns_when_inherited_but_still_opens_the_app[True]` |
| M2 | Aviso do backend movido para DEPOIS dos efeitos de bind | `hermes_cli/web_server.py` | `dcc5064f74a9…79a6565` | MORTO (4✓ 1✗) | `…::test_backend_start_server_warns_before_any_bind_side_effect[True]` |
| M3 | Guarda de escrita HTTP desligada (`APIRouter()` sem dependência) | `plugins/kanban/dashboard/plugin_api.py` | `d654f0eecd07…13dbfb` | MORTO (1✓ 5✗) | 4 arms de `test_kanban_launch_identity.py` + `test_launch_identity_live.py` (serve REAL) |
| M4 | Inverso: guarda cerca TAMBÉM a leitura (sensor que acusa sempre) | `plugins/kanban/dashboard/plugin_api.py` | `2ea19c53cfdf…63fcbb` | MORTO (1✓ 5✗) | os mesmos 5, por negarem a leitura que deve continuar aberta |

M4 é o mutante que importa contra o vício do conserto: prova que a suíte não
aceita "negar tudo". M1 e M2 provam o par simétrico no lado do aviso — em ambos
o arm NÃO-restrito continuou verde, então o sensor não acusa todo mundo.

## Controle positivo, no mesmo estímulo

Cada teste de aviso é `@pytest.mark.parametrize("restricted", [True, False])`
sobre o MESMO caminho de código: só a presença de `HERMES_DELEGATED_CHILD_CONTEXT`
muda. Sob M1 e M2 o arm `[False]` permaneceu verde — a falha foi só do arm que
deveria acusar.

## Restauração

sha256 dos 4 arquivos ANTES e DEPOIS da bateria (`diff` limpo):

```
ead797dffd7e8875f01f5f56d158250ff34e8dfa0ea85f0e533c3b62a82b104c  hermes_cli/main_desktop.py
561751713e8ee33d164e8339e895e411817d0ccb1573854818922b2e4cacff74  hermes_cli/web_server.py
b153616789f76b652ca7a22d468c211b8da77754f5fb58cb0ba5ba483d27099f  plugins/kanban/dashboard/plugin_api.py
354822b960736558c3fc1590ebc244e90bd36c4cc6c464082f2cc96f60763dbf  hermes_cli/interactive_launch_context.py
```

RESTAURACAO OK: sha256 idêntico nos 4 arquivos.

## Bateria completa pós-restauração

`docs/evidencia/t_e9aedb24/green-pos-restauracao.log`:
8 arquivos, **119 tests passed, 0 failed**, 9 skipped (macos_only/windows_only,
que rodam na lane tests-os do CI), 26.3s, uid=502.
