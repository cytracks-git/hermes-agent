"""Populacao real das branches nao publicadas, e o CUSTO de medi-las.

SO LEITURA. Nao escreve em repo nenhum nem toca board nenhum.

Duas perguntas que decidem o conserto da rodada 4:

  (a) RECORTE — medir `refs/heads` em vez de so o HEAD fecha G1/G2, mas quantas
      branches ALHEIAS ao card passariam a travar o fechamento? O numero decide;
      presumir aqui e o que produz gate paranoico.

  (b) CUSTO — quantos subprocessos custa. A versao ingenua
      (`rev-list --count <branch> --not --remotes` POR BRANCH) foi medida
      estourando 420s ao varrer os 91 worktrees deste host. A versao usada aqui
      e a mesma que o gate passa a usar: UM `rev-list --branches --source`,
      independente do numero de branches.

Recortes comparados:
  R0  toda branch local com commit que nenhum remoto anuncia
  R1  R0 menos as que NOMEIAM um task id (recorte por dono)
  R2  R1 menos as paradas ha mais de X (recorte por janela do card)
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

TASK_ID_RE = re.compile(r"t_[0-9a-f]{8}")
PULAR = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}

CHAMADAS = 0


def git(repo: Path, *a: str, timeout: int = 60):
    global CHAMADAS
    CHAMADAS += 1
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *a], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, check=False)
    except (subprocess.SubprocessError, OSError):
        return None


def eh_repo(p: Path) -> bool:
    r = git(p, "rev-parse", "--is-inside-work-tree")
    return bool(r and r.returncode == 0 and r.stdout.strip() == "true")


def worktrees_de(repo: Path) -> list[Path]:
    r = git(repo, "worktree", "list", "--porcelain")
    if r is None or r.returncode != 0:
        return []
    return [Path(l[len("worktree "):].strip())
            for l in r.stdout.splitlines() if l.startswith("worktree ")]


def repos_do_board(raiz: Path, prof: int = 3) -> list[Path]:
    if not raiz.is_dir():
        return []
    achados: list[Path] = []
    fronteira = [(raiz, 0)]
    while fronteira:
        atual, nivel = fronteira.pop(0)
        try:
            filhos = sorted(p for p in atual.iterdir() if p.is_dir() and not p.is_symlink())
        except OSError:
            continue
        for f in filhos:
            if f.name in PULAR:
                continue
            if (f / ".git").exists():
                achados.append(f)
                continue
            if nivel + 1 < prof:
                fronteira.append((f, nivel + 1))
    return achados


class NaoMedido(Exception):
    """A sonda nao rodou. NAO e o mesmo que o repo estar limpo."""


def nao_publicadas_de_uma_vez(repo: Path) -> dict[str, tuple[int, int]]:
    """{branch: (commits_nao_publicados, epoch_do_ultimo_commit)} em 2 subprocessos.

    `git log --source --format=%S` marca cada commit com a ref por onde a
    travessia chegou nele, o que da a distribuicao por branch sem um
    subprocesso por branch. Medido no clm360 (104 branches): 0,1s contra 7,7s
    da versao por-branch; nos 98 repos deste host a por-branch nao terminou em
    420s.

    CUIDADO medido: `rev-list --branches --not --remotes --source` sai com
    ERRO DE USO (`usage: git rev-list`) — `--source` so vale em `git log`. A
    primeira versao deste medidor engolia esse rc!=0 como lista vazia e
    reportou `R0=0 branches` com 8 commits orfaos debaixo do nariz. Por isso
    aqui a falha vira NaoMedido, nunca dicionario vazio.
    """
    datas: dict[str, int] = {}
    r = git(repo, "for-each-ref", "--format=%(refname:short)%09%(committerdate:unix)",
            "refs/heads")
    if r is None or r.returncode != 0:
        raise NaoMedido(f"for-each-ref falhou em {repo}")
    for linha in r.stdout.splitlines():
        if "\t" in linha:
            nome, quando = linha.split("\t", 1)
            datas[nome] = int(quando.strip() or 0)
    if not datas:
        return {}

    r = git(repo, "log", "--branches", "--not", "--remotes", "--source", "--format=%S")
    if r is None or r.returncode != 0:
        raise NaoMedido(f"log --source falhou em {repo}: "
                        f"{(r.stderr if r else '')[:120]}")
    contagem: dict[str, int] = {}
    for linha in r.stdout.splitlines():
        nome = linha.strip()
        if nome:
            contagem[nome] = contagem.get(nome, 0) + 1
    return {b: (n, datas.get(b, 0)) for b, n in contagem.items()}


def main() -> int:
    t0 = time.time()
    agora = int(time.time())
    janelas = {"6h": 6 * 3600, "24h": 24 * 3600, "7d": 7 * 24 * 3600}

    ancoras = [Path.home() / ".hermes" / "hermes-agent", Path.home() / "Downloads" / "clm360"]
    cands: list[Path] = []
    for a in ancoras:
        if a.is_dir() and eh_repo(a):
            cands.append(a)
            cands.extend(worktrees_de(a))
    boards = Path.home() / ".hermes" / "kanban" / "boards"
    for ws in sorted(boards.glob("*/workspaces")) if boards.is_dir() else []:
        cands.extend(repos_do_board(ws))

    vistos: set[str] = set()
    repos: list[Path] = []
    for c in cands:
        try:
            chave = str(c.resolve())
        except OSError:
            continue
        if chave in vistos:
            continue
        vistos.add(chave)
        repos.append(c)

    print(f"repos git enumerados: {len(repos)}"
          f"  (ancoras + `git worktree list` + workspaces do board)\n")

    chaves = ["R0", "R1", *[f"R2/{k}" for k in janelas]]
    tot = {k: 0 for k in chaves}
    repos_com: dict[str, set[str]] = {k: set() for k in chaves}
    detalhe: list[str] = []
    nao_medidos: list[str] = []

    for repo in repos:
        try:
            nb = nao_publicadas_de_uma_vez(repo)
        except NaoMedido as exc:
            nao_medidos.append(str(exc))
            continue
        if not nb:
            continue
        head = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        head_nome = head.stdout.strip() if head and head.returncode == 0 else "?"
        linhas = []
        for nome, (n, quando) in sorted(nb.items()):
            nomeia_card = bool(TASK_ID_RE.findall(nome))
            idade = (agora - quando) if quando else 10 ** 9
            marcas = []
            tot["R0"] += 1
            repos_com["R0"].add(str(repo))
            if not nomeia_card:
                tot["R1"] += 1
                repos_com["R1"].add(str(repo))
                marcas.append("R1")
                for k, seg in janelas.items():
                    if idade <= seg:
                        tot[f"R2/{k}"] += 1
                        repos_com[f"R2/{k}"].add(str(repo))
                        marcas.append(f"R2/{k}")
            linhas.append(
                f"      {nome:<44} {n:>4} commit(s) idade={min(idade // 3600, 99999):>6}h"
                f" {'HEAD' if nome == head_nome else '    '} {','.join(marcas) or 'so-R0'}")
        detalhe.append(f"  {repo}\n" + "\n".join(linhas))

    print("\n".join(detalhe))
    print("\n" + "=" * 78)
    print("QUANTAS branches nao publicadas cada recorte alcanca")
    print("=" * 78)
    for k in chaves:
        print(f"  {k:<10} branches={tot[k]:>5}   repos afetados={len(repos_com[k]):>4}")
    print("\nR0-R1 = branches que NOMEIAM um card (recorte barato por dono).")
    print("R1-R2 = branches paradas, anteriores a janela do card que fecha.")
    if nao_medidos:
        print(f"\nNAO MEDIDO em {len(nao_medidos)} repo(s) — a sonda nao rodou, e isso")
        print("NAO quer dizer que estejam limpos:")
        for m in nao_medidos[:10]:
            print(f"  {m}")
    print(f"\nCUSTO: {CHAMADAS} subprocessos git, {time.time() - t0:.1f}s para "
          f"{len(repos)} repos (a versao por-branch nao terminou em 420s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
