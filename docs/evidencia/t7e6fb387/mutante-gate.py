#!/usr/bin/env python3
"""Mutante: testes NOVOS contra o codigo VELHO.

Copia o pacote do worktree, sobrescreve kanban_db.py e kanban_tools.py
com a versao HEAD, e roda os testes C1-C9. Se o codigo VELHO passar
C1/C4, o teste nao mede a classe do defeito.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WT = Path("/Users/farantes/atlas/wt/gate-evidencia")
PY = WT / ".venv" / "bin" / "python"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="mutante-gate-"))
    try:
        src_pkg = tmp / "src"
        src_pkg.mkdir()
        for name in ("hermes_cli", "tools"):
            shutil.copytree(
                WT / name,
                src_pkg / name,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        for rel in ("hermes_cli/kanban_db.py", "tools/kanban_tools.py"):
            blob = subprocess.check_output(
                ["git", "-C", str(WT), "show", f"HEAD:{rel}"]
            )
            (src_pkg / rel).write_bytes(blob)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(src_pkg) + os.pathsep + env.get("PYTHONPATH", "")
        cmd = [
            str(PY), "-m", "pytest",
            str(WT / "tests/hermes_cli/test_kanban_evidence_gate.py"),
            "-q", "--tb=line",
        ]
        print("MUTANTE: testes NOVOS contra kanban_db.py e kanban_tools.py da HEAD")
        r = subprocess.run(cmd, cwd=str(WT), env=env, timeout=180)
        print(f"exit={r.returncode} (esperado != 0: o codigo VELHO tem de falhar C1/C4)")
        return r.returncode
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
