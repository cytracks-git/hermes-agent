## O defeito

O repositório tem **98 worktrees**, e **92 deles carregam commits que não estão na main** — 1608 no total. O `atlas.local` monta um desses branches há 3 dias, ent⟪HERMES-CONTEXT-COMPRESSION: 5,455 of 5,655 chars omitted here by Hermes's context compressor. This is NOT part of the original tool call and must never be reproduced in new output — always write full, untruncated content.⟫

---

## ⚠️ NÃO MEDIDO — especificação destruída, não recuperada

**O corpo acima está incompleto.** Tudo que vinha depois de `sses branches há 3 dias, ent`
foi substituído por um marcador de compressão de contexto: **5,455 dos 5,655 chars
originais nunca chegaram ao disco** (sobraram 176).

Causa raiz (medida em `t_00542312`): o modelo IMITOU o marcador terminal que
`agent/context_compressor.py` usa para encurtar a JANELA DE CONTEXTO, e escreveu o
texto imitado no banco. Classe #83714, documentada no próprio compressor (L1416-1420).
Não era exibição: o dado durável foi destruído na escrita.

**Recuperação: ESGOTADA, sem fonte real.** Medido em `t_00542312`:

| fonte | resultado |
|---|---|
| 10 backups `kanban.db.bak-*` | todos de 2026-09-19, **anteriores** ao dano (2026-09-22/23) — não contêm o card |
| 294 dumps de sessão (`~/.hermes/sessions` + perfis) | âncora do head sobrevivente não encontrada |
| 222 logs de worker + anexos + WAL | não encontrada |
| `task_events` | payload de `created` só tem metadado (assignee/status), não o corpo |

**O conteúdo perdido NÃO foi reconstituído de memória ou inferência** — isso apagaria
o rastro da perda e é pior que o buraco. Só o autor original pode reescrever o que
esta seção dizia.

**Correção da causa aplicada** (branch `fix/kanban-corpo-comprimido-durable`): a
fronteira de admissão `hermes_cli/kanban_task_body.py` recusa a escrita ANTES de
persistir, nas 6 fronteiras. Dano novo desta classe não acontece mais; este registro
aqui é dano PASSADO, preservado de propósito com o rastro intacto.
