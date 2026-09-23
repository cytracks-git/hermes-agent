---
sidebar_position: 24
title: "Scripts library"
description: "Browse the scripts already on your machine from inside Hermes — what each one does, how to run it, and whether it is committed, reviewed and published."
---

# Scripts library

A read-only catalogue of the script files already on disk, reachable from inside
Hermes. It answers four questions about each script, in one place:

- **What does it do?** — documentation read out of the file itself.
- **How do I run it?** — a copyable command, built from the interpreter and the
  executable bit.
- **What does it need?** — dependencies, environment, permissions, exit codes,
  limits and tests, when the author documented them.
- **What state is it in?** — on disk, committed, reviewed, published — each
  answer next to the evidence behind it.

It shows you what exists. It does not run anything, and it has no route that
writes, uploads or deletes.

## Turning it on

The library ships as a plugin that is **off by default**.

- **Desktop app** — Capabilities ▸ Plugins ▸ **Scripts**, then the sidebar entry
  (or `⌘K` → "Scripts: Open library").
- **Dashboard** (`hermes dashboard`) — Plugins ▸ **Scripts**.

Both surfaces read the same catalogue through the same backend; neither keeps a
copy of its own.

## Where it looks

Two locations are scanned without any configuration:

| Location | Path |
| --- | --- |
| Hermes home | `<hermes home>/scripts` |
| Checkout | `<repo>/scripts`, when Hermes runs from a git checkout |

Add your own in `config.yaml`:

```yaml
scripts_library:
  roots:
    - ~/work/ops-scripts               # a bare path
    - path: /srv/shared/scripts        # or a path with a label
      label: Shared team scripts
    - ${TEAM_SCRIPTS}                  # env vars and ~ are expanded
```

A configured directory that does not exist is **reported, not skipped**: the
library says "Configured location not found: …" instead of quietly showing a
shorter list. "Nothing here" and "that directory is gone" are different problems.

Files are catalogued by extension (`.sh`, `.bash`, `.zsh`, `.fish`, `.py`, `.rb`,
`.pl`, `.js`, `.mjs`, `.cjs`, `.ts`, `.ps1`). Dotfiles, `node_modules`, `.git`,
`__pycache__`, `venv` and friends are skipped, and **no symlink inside a root is
followed — files included**. A link is neither walked nor catalogued nor served:
`scripts/innocent.py -> ~/.hermes/.env` would otherwise pass the extension filter
and hand the credential over as that script's source. Reads also open with
`O_NOFOLLOW`, so a file swapped for a link after the scan fails instead of
leaking.

## Where the documentation comes from

The file itself, **parsed and never executed**:

- **Python** — the module docstring, read with `ast.parse`. Parsing builds a
  syntax tree without running the module, so cataloguing a script cannot trigger
  its side effects. A file that does not parse falls back to its header comments.
- **Shell and everything else** — the comment block at the top of the file, after
  the shebang.

Headed sections are picked up when the author wrote them:

```python
"""Collect disk usage per profile.

Usage:
  disk-usage.py --profile default

Dependencies:
  python3.11+, psutil

Exit codes:
  0  ok
  2  profile not found
"""
```

`Usage`, `Inputs`, `Outputs`, `Dependencies`, `Environment`, `Permissions`,
`Exit codes`, `Limits`, `Tests` and `Notes` are recognised, in several spellings
(`Requires:` and `Depends on:` both mean dependencies; `Arguments:` and
`Parameters:` both mean inputs). A section that is not there is not shown — the
library never fills in a plausible-looking blank.

A script with no documentation reads as **"This script has no documentation
yet."** That is the honest answer, and it is also the nudge.

## What "state" means

Each stage carries its own evidence, so you can check the verdict instead of
trusting it:

| Stage | Says yes when | Evidence shown |
| --- | --- | --- |
| **On disk** | the file is readable | the path it was read from |
| **Committed** | tracked by git and matching the last commit | the commit sha and subject |
| **Reviewed** | a pull-request merge commit carries this commit to the tracked remote | the PR number and merge commit |
| **Published** | the commit is an ancestor of the tracked remote branch | the remote ref |

Three consequences worth knowing:

- **A modified file is not described by its commit.** Edit a committed script and
  Committed reports **Edited**, not Yes — the commit on GitHub no longer
  describes the bytes on your disk.
- **Publication is not review.** A commit pushed straight to a branch reports
  published, and reviewed stays *Not measured* with the reason spelled out.
- **Not measured is a real answer.** No remote, no git, a repo the scan cannot
  read: the library says so, with the reason. It never turns an absent
  measurement into a pass.

There is deliberately **no "installed" stage**. Nothing here measures
installation, so nothing here claims it.

## The REST surface

Mounted at `/api/plugins/scripts-library/`. Every route is `GET`:

| Route | Returns |
| --- | --- |
| `GET /catalog` | every script, with `q`, `language` and `root` filters |
| `GET /scripts/{id}` | one script: documentation, sections, run command, git facts, lifecycle |
| `GET /scripts/{id}/source` | the file's text, bounded and truncation-flagged |
| `GET /health` | whether the catalogue can be built, and what is in the way |

`{id}` is an opaque digest resolved against a freshly scanned catalogue, never a
path. A path-shaped id names nothing, whatever it points at — traversal is not
filtered here, it is unrepresentable.

## Limits

- Bounded at 2,000 files and 6 directory levels per root; a larger tree reports
  `truncated` rather than scanning forever.
- Documentation is read from the first 64 KB of a file.
- Git facts come from the repository the file lives in. A file outside any
  repository reports *not available* with the reason, never a guessed state.
