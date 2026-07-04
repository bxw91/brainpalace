---
name: brainpalace-lsp
description: Manage LSP language servers used for exact cross-file graph edges
parameters:
skills:
  - using-brainpalace
last_validated: 2026-07-03
---

# Manage LSP Language Servers

## Purpose

Manage the LSP language servers BrainPalace uses to resolve exact cross-file
call edges in the code graph. `install` installs the language server for a
language (Python -> pyright) via the first available package manager (pipx,
npm, or an in-venv pip), prompting for consent unless `--yes` is passed. It runs
the install with a timeout and confirms success by re-probing your PATH; if the
server lands in a directory that is not on PATH, it names the directory to add.
BrainPalace also offers this install when you enable graph indexing / LSP during
`brainpalace init` (interactive prompt) or `brainpalace doctor`.

## Usage

```
/brainpalace:brainpalace-lsp install [--lang <language>] [--yes]
```

### Examples

```
/brainpalace:brainpalace-lsp install            # Prompt, then install pyright
/brainpalace:brainpalace-lsp install --yes      # Install without prompting (CI-safe)
```

## Execution

Run the CLI command for the requested language server:

```bash
brainpalace lsp install --lang python --yes
```

Exit code is 0 on success (already present, installed, or installed-but-not-on-PATH)
or when the user declines, and non-zero when the install fails or no package
manager is available.
