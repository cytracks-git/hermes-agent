"""De qual arvore o processo do WORKER carrega hermes_cli? Medido, nao suposto.

Por que existe
--------------
O dispatcher inicia o worker com ``python -m hermes_cli.main`` e ``cwd`` =
workspace do card. Com ``-m``, o CPython poe o diretorio de trabalho em
``sys.path[0]``; se esse diretorio for um checkout do proprio Hermes (que e o
caso de um worktree deste repositorio), o pacote do WORKTREE sombreia o da
instalacao compartilhada. Quatro rodadas deste card afirmaram "patch NAO
instalado" medindo ``grep -c waiting_approval`` no arquivo da INSTALACAO --
alvo errado se o processo carrega outro arquivo.

Esta sonda responde, no processo real, tres perguntas separadas:

1. de qual caminho vem ``hermes_cli`` / ``tools`` / ``tui_gateway``;
2. se o codigo carregado contem o patch (marcador ``waiting_approval``);
3. o que o mesmo import resolveria com ``sys.path`` SEM o cwd -- o controle
   negativo que separa "o worktree sombreia" de "a instalacao ja tem o patch".

Uso: python3 sonda_origem_do_codigo.py   (rodar com o MESMO cwd do worker)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

MODULOS = ("hermes_cli", "tools", "tui_gateway", "plugins")
MARCADOR = "waiting_approval"


def _origem(nome: str) -> dict:
    import importlib

    try:
        mod = importlib.import_module(nome)
    except Exception as exc:  # pragma: no cover - diagnostico
        return {"modulo": nome, "erro": repr(exc)}
    caminho = getattr(mod, "__file__", None) or (list(getattr(mod, "__path__", [])) or [None])[0]
    return {"modulo": nome, "arquivo": caminho}


def _tem_patch(raiz: Path) -> dict:
    alvo = raiz / "hermes_cli" / "kanban_db.py"
    if not alvo.exists():
        return {"arquivo": str(alvo), "existe": False}
    texto = alvo.read_text(encoding="utf-8", errors="replace")
    return {"arquivo": str(alvo), "existe": True, "ocorrencias_marcador": texto.count(MARCADOR)}


def main() -> int:
    saida = {
        "pid": os.getpid(),
        "cwd": os.getcwd(),
        "executavel": sys.executable,
        "sys_path_0": sys.path[0] if sys.path else None,
        "PYTHONPATH": os.environ.get("PYTHONPATH"),
        "PYTHONSAFEPATH": os.environ.get("PYTHONSAFEPATH"),
        "flag_safe_path": bool(getattr(sys.flags, "safe_path", 0)),
        "origens": [_origem(n) for n in MODULOS],
    }

    # Controle negativo: o MESMO import, com o cwd fora do sys.path (-P). Se o
    # arquivo mudar de arvore, o sombreamento esta provado; se nao mudar, a
    # instalacao e que serve o codigo.
    codigo = (
        "import json,importlib;"
        "print(json.dumps({n: getattr(importlib.import_module(n), '__file__', None) "
        "for n in ('hermes_cli','tools','tui_gateway')}))"
    )
    for rotulo, argv in (
        ("com_cwd", [sys.executable, "-c", codigo]),
        ("sem_cwd", [sys.executable, "-P", "-c", codigo]),
    ):
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=120, cwd=os.getcwd())
            saida[rotulo] = {
                "rc": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip()[-400:],
            }
        except Exception as exc:  # pragma: no cover - diagnostico
            saida[rotulo] = {"erro": repr(exc)}

    saida["marcador_no_cwd"] = _tem_patch(Path(os.getcwd()))
    saida["marcador_na_instalacao"] = _tem_patch(Path.home() / ".hermes" / "hermes-agent")

    print(json.dumps(saida, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
