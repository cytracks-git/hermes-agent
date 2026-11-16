"""Mutantes do instrumento baseline.py: cada sabotagem tem de reprovar controle_baseline.py.

Copia baseline.py sabotado + controle para diretorio temporario e roda. rc=1 do
controle = mutante morto. Inclui o defeito original (kind='transient_retry').
Uso (venv do Hermes): python mutantes_baseline.py <worktree>
"""
import os, shutil, subprocess, sys, tempfile
from pathlib import Path

WT = Path(sys.argv[1]).resolve()
EV = Path(__file__).resolve().parent
SRC = (EV / "baseline.py").read_text()
MUTANTES = {
    "defeito_velho_transient_retry": (
        "\"SELECT COUNT(*) FROM task_events WHERE kind='unblocked' \"\n"
        "            \"AND json_extract(payload,'$.auto')=? AND created_at >= ?\", (AUTO_MARKER, desde)",
        "\"SELECT COUNT(*) FROM task_events WHERE kind='transient_retry' \"\n"
        "            \"AND ?=? AND created_at >= ?\", (AUTO_MARKER, AUTO_MARKER, desde)"),
    "conta_todo_unblocked": (
        "\"AND json_extract(payload,'$.auto')=? AND created_at >= ?\", (AUTO_MARKER, desde)",
        "\"AND ?=? AND created_at >= ?\", (AUTO_MARKER, AUTO_MARKER, desde)"),
    "classifica_tudo_mao": ("auto = nxt[\"kind\"] == \"unblocked\" and", "auto = False and"),
    "marcador_errado": ("AUTO_MARKER = \"transient_redispatch\"", "AUTO_MARKER = \"transient_retry\""),
}
vivos = []
for nome, (velho, novo) in MUTANTES.items():
    if SRC.count(velho) != 1:
        print("ERRO ancora nao unica:", nome)
        sys.exit(2)
    d = Path(tempfile.mkdtemp(prefix="c2-mut-", dir=os.environ.get("TMPDIR")))
    try:
        (d / "baseline.py").write_text(SRC.replace(velho, novo))
        shutil.copy(EV / "controle_baseline.py", d)
        r = subprocess.run([sys.executable, str(d / "controle_baseline.py"), str(WT)],
                           capture_output=True, text=True, cwd=WT)
    finally:
        shutil.rmtree(d)
    falhas = [l[:80] for l in r.stdout.splitlines() if l.startswith("FALHA")]
    morto = r.returncode == 1 and falhas
    print("morto" if morto else "VIVO ", nome, f"rc={r.returncode}", falhas[:2])
    if not morto:
        vivos.append(nome)
print(f"RESULTADO: {len(MUTANTES) - len(vivos)}/{len(MUTANTES)} mortos", vivos or "")
sys.exit(1 if vivos else 0)
