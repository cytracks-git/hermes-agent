"""RECORTE por REFLOG: quantas branches o gate alcancaria com este predicado.

SO LEITURA. Nao escreve em repo nem em board.

O medidor `pop-branches-rodada4.py` mostrou que medir TODAS as `refs/heads`
alcanca 638 branches nao publicadas em 93 repos deste host — quase todas
compartilhadas pelos 87 worktrees do clm360, de cards e meses alheios. Travar
o fechamento nelas seria a paranoia que o card proibe explicitamente.

Este medidor testa o recorte proposto:

    toda branch que o HEAD DESTE worktree apontou DENTRO da janela do card

Fonte: `git reflog show HEAD`, que e POR WORKTREE (arquivo proprio em
`.git/worktrees/<nome>/logs/HEAD`, confirmado neste host) e e escrito pelo
git a cada checkout/commit — inclusive pelo `git checkout main` do bypass B4.
A janela vem de `task_runs.started_at`, que o board escreve.

A pergunta que este medidor responde: com esse recorte, quantas branches
entram? Se o numero ficar perto de 638, o recorte nao recorta nada.
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

CHAMADAS = 0
JANELAS = {"6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600}
RE_CHECKOUT = re.compile(r"checkout: moving from (\S+) to (\S+)")


def git(repo: Path, *a: str, timeout: int = 60):
    global CHAMADAS
    CHAMADAS += 1
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *a], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except (subprocess.SubprocessError, OSError):
        return None


class NaoMedido(Exception):
    """A sonda nao rodou. NAO e o mesmo que estar limpo."""


def branches_tocadas(repo: Path, desde: int) -> set[str]:
    """Branches que o HEAD deste worktree apontou desde `desde` (epoch).

    Le o reflog do HEAD com data unix. Cada entrada de `checkout: moving from
    A to B` doa DUAS branches (a que saiu e a que entrou); `commit:` e
    `reset:` confirmam a branch corrente no momento.
    """
    r = git(repo, "reflog", "show", "HEAD", "--date=unix")
    if r is None:
        raise NaoMedido(f"reflog nao rodou em {repo}")
    if r.returncode != 0:
        # Repo sem reflog (clone raso, repo novo) e resposta conclusiva: vazio.
        if "no reflog" in (r.stderr or "").lower() or not (r.stderr or "").strip():
            return set()
        raise NaoMedido(f"reflog falhou em {repo}: {(r.stderr or '')[:120]}")

    atual = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    corrente = atual.stdout.strip() if atual and atual.returncode == 0 else ""
    tocadas: set[str] = set()
    if corrente and corrente != "HEAD":
        tocadas.add(corrente)

    for linha in r.stdout.splitlines():
        m = re.search(r"HEAD@\{(\d+)\}", linha)
        if not m:
            continue
        if int(m.group(1)) < desde:
            break  # reflog e cronologico decrescente
        mv = RE_CHECKOUT.search(linha)
        if mv:
            tocadas.update({mv.group(1), mv.group(2)})
    return {b for b in tocadas if b and b != "HEAD" and not re.fullmatch(r"[0-9a-f]{7,40}", b)}


def nao_publicadas(repo: Path, branches: set[str]) -> dict[str, int]:
    """Das `branches`, as que tem commit que nenhum remoto anuncia."""
    out: dict[str, int] = {}
    for b in sorted(branches):
        r = git(repo, "rev-parse", "--verify", f"refs/heads/{b}")
        if r is None or r.returncode != 0:
            continue  # branch apagada depois: nada a cobrar
        c = git(repo, "rev-list", "--count", b, "--not", "--remotes")
        if c is None:
            raise NaoMedido(f"rev-list nao rodou em {repo}")
        if c.returncode != 0:
            raise NaoMedido(f"rev-list falhou em {repo}/{b}")
        n = int(c.stdout.strip() or 0)
        if n > 0:
            out[b] = n
    return out


def eh_repo(p: Path) -> bool:
    r = git(p, "rev-parse", "--is-inside-work-tree")
    return bool(r and r.returncode == 0 and r.stdout.strip() == "true")


def enumerar() -> list[Path]:
    ancoras = [Path.home() / ".hermes" / "hermes-agent", Path.home() / "Downloads" / "clm360"]
    cands: list[Path] = []
    for a in ancoras:
        if a.is_dir() and eh_repo(a):
            cands.append(a)
            r = git(a, "worktree", "list", "--porcelain")
            if r and r.returncode == 0:
                cands.extend(Path(l[len("worktree "):].strip())
                             for l in r.stdout.splitlines() if l.startswith("worktree "))
    vistos: set[str] = set()
    out: list[Path] = []
    for c in cands:
        try:
            k = str(c.resolve())
        except OSError:
            continue
        if k not in vistos and c.is_dir():
            vistos.add(k)
            out.append(c)
    return out


def main() -> int:
    t0 = time.time()
    agora = int(time.time())
    repos = enumerar()
    print(f"worktrees medidos: {len(repos)}\n")

    tot = {k: 0 for k in JANELAS}
    repos_com: dict[str, set[str]] = {k: set() for k in JANELAS}
    nao_medidos: list[str] = []
    detalhe: list[str] = []

    for repo in repos:
        linhas = []
        for jk, seg in JANELAS.items():
            try:
                tocadas = branches_tocadas(repo, agora - seg)
                sujas = nao_publicadas(repo, tocadas)
            except NaoMedido as exc:
                nao_medidos.append(str(exc))
                continue
            if sujas:
                tot[jk] += len(sujas)
                repos_com[jk].add(str(repo))
                if jk == "24h":
                    linhas.append("      " + ", ".join(
                        f"{b} ({n})" for b, n in sorted(sujas.items())))
        if linhas:
            detalhe.append(f"  {repo}\n" + "\n".join(linhas))

    print("Branches NAO publicadas que o HEAD do worktree tocou nas ultimas 24h:")
    print("\n".join(detalhe) if detalhe else "  (nenhuma)")
    print("\n" + "=" * 78)
    print("RECORTE POR REFLOG — alcance por janela")
    print("=" * 78)
    for jk in JANELAS:
        print(f"  janela={jk:<5} branches={tot[jk]:>4}   worktrees afetados={len(repos_com[jk]):>3}")
    print("\nComparacao: medir TODAS as refs/heads alcanca 638 branches em 93 repos")
    print("(pop-branches-rodada4.py). O recorte por reflog e o que separa")
    print("'o que ESTE card teve nas maos' de 'tudo que existe no repo'.")
    if nao_medidos:
        print(f"\nNAO MEDIDO em {len(nao_medidos)} caso(s):")
        for m in nao_medidos[:10]:
            print(f"  {m}")
    print(f"\nCUSTO: {CHAMADAS} subprocessos git, {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
