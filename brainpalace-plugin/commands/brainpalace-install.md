---
name: brainpalace-install
description: Install BrainPalace packages using pipx, uv, pip, or conda
parameters: []
context: brainpalace
agent: setup-assistant
skills:
  - configuring-brainpalace
last_validated: 2026-07-11
---

# Install BrainPalace Packages

## STOP - READ THIS FIRST

**DO NOT RUN ANY INSTALLATION COMMANDS YET.**

You MUST ask the user which installation method they prefer using the AskUserQuestion tool BEFORE doing anything else.

## Step 1: Ask User for Installation Method

**THIS IS MANDATORY. DO NOT SKIP THIS STEP.**

Use the AskUserQuestion tool with this exact structure:

```json
{
  "questions": [{
    "question": "Which installation method do you prefer for BrainPalace?",
    "header": "Install via",
    "options": [
      {
        "label": "pipx (Recommended)",
        "description": "Install globally in an isolated environment. No activation needed."
      },
      {
        "label": "uv",
        "description": "Fast, modern Python tool installer. Good for power users."
      },
      {
        "label": "pip (venv)",
        "description": "Install into a local virtual environment. Requires activation."
      },
      {
        "label": "conda",
        "description": "For conda users. Creates a conda environment with pip inside."
      }
    ],
    "multiSelect": false
  }]
}
```

**STOP HERE AND WAIT FOR THE USER'S RESPONSE.**

Do not proceed until you have called AskUserQuestion and received the user's selection.

---

## Step 1.5: Resolve Version

After receiving the user's installation method choice, resolve the latest version from PyPI:

```bash
# Resolve helper script path (installed plugin or local repo)
PYPI_VERSION_SCRIPT=$(find ~/.claude/plugins/brainpalace/scripts ~/.claude/skills/brainpalace/scripts brainpalace-plugin/scripts -name "bp-pypi-version.sh" 2>/dev/null | head -1)

if [ -n "$PYPI_VERSION_SCRIPT" ]; then
  VERSION=$("$PYPI_VERSION_SCRIPT")
  echo "Latest available: $VERSION"
else
  echo "bp-pypi-version.sh not found — falling back to inline version lookup"
  VERSION=$(curl -sf https://pypi.org/pypi/brainpalace-rag/json | python3 -c "import sys,json; print(json.load(sys.stdin)['info']['version'])")
  echo "Latest available: $VERSION"
fi
```

Then ask user for version preference using AskUserQuestion:

```json
{
  "questions": [{
    "question": "Which version of BrainPalace do you want to install?",
    "header": "Version",
    "options": [
      {
        "label": "Latest ($VERSION) (Recommended)",
        "description": "Install the latest stable release from PyPI."
      },
      {
        "label": "Specific version",
        "description": "I'll show available versions and ask which one."
      }
    ],
    "multiSelect": false
  }]
}
```

If user selects "Specific version", show available versions:

```bash
curl -sf https://pypi.org/pypi/brainpalace-rag/json | python3 -c "
import sys,json
releases = list(json.load(sys.stdin)['releases'].keys())
releases.sort(key=lambda v: [int(x) for x in v.split('.')], reverse=True)
print('Available versions:', ', '.join(releases[:8]))
"
```

Then ask the user to enter the specific version they want and store it in `$VERSION`.

---

## Step 2: Check Python Version

Only after receiving the user's installation method choice:

```bash
python --version
```

Requires Python 3.10+. If lower, tell user to upgrade first.

---

## Step 3: Execute Based on User's Selection

### If user selected "pipx (Recommended)"

1. Check/install pipx:
   ```bash
   pipx --version 2>/dev/null || python -m pip install --user pipx && python -m pipx ensurepath
   ```

2. Install BrainPalace with pinned version (bypass pip's index cache so a
   just-published version isn't masked by a stale cached simple-index page).
   Pin all three packages so pip resolves in one shot instead of backtracking
   for minutes (the dashboard pins the CLI with an exact `==`, so unpinned
   siblings make pip fetch+reject older candidates):
   ```bash
   pipx install --pip-args="--no-cache-dir brainpalace-rag==$VERSION brainpalace-dashboard==$VERSION" brainpalace-cli==$VERSION
   ```
   *On Python <3.12 the dashboard isn't a dependency — drop the
   `brainpalace-dashboard==$VERSION` pin.*

3. Verify (user may need to restart terminal):
   ```bash
   brainpalace --version
   ```

### If user selected "uv"

1. Check/install uv:
   ```bash
   UV_CHECK_SCRIPT=$(find ~/.claude/plugins/brainpalace/scripts ~/.claude/skills/brainpalace/scripts brainpalace-plugin/scripts -name "bp-uv-check.sh" 2>/dev/null | head -1)

   if [ -n "$UV_CHECK_SCRIPT" ]; then
     UV_CHECK_OUTPUT=$("$UV_CHECK_SCRIPT")
     echo "$UV_CHECK_OUTPUT"
     if ! echo "$UV_CHECK_OUTPUT" | grep -q "available"; then
       pipx install uv   # or: pip install uv; see https://docs.astral.sh/uv/getting-started/installation/
     fi
   else
     uv --version 2>/dev/null || pipx install uv || pip install uv
   fi
   ```

2. Install BrainPalace with pinned version (bypass uv's cache for the same
   reason). Pin all three so the resolver doesn't backtrack:
   ```bash
   uv tool install --no-cache brainpalace-cli==$VERSION --with brainpalace-rag==$VERSION --with brainpalace-dashboard==$VERSION
   ```
   *On Python <3.12 the dashboard isn't a dependency — drop the
   `--with brainpalace-dashboard==$VERSION`.*

3. Verify:
   ```bash
   brainpalace --version
   ```

### If user selected "pip (venv)"

1. Create virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # macOS/Linux
   ```

2. Install packages with pinned version (bypass pip's index cache). Pin all
   three so the resolver doesn't backtrack:
   ```bash
   pip install --no-cache-dir brainpalace-rag==$VERSION brainpalace-cli==$VERSION brainpalace-dashboard==$VERSION
   ```
   *On Python <3.12 the dashboard isn't a dependency — drop the
   `brainpalace-dashboard==$VERSION` pin.*

3. Verify:
   ```bash
   brainpalace --version
   ```

4. **Tell user:** Must run `source .venv/bin/activate` before using brainpalace.

### If user selected "conda"

1. Create conda environment:
   ```bash
   conda create -n brainpalace python=3.12 -y
   conda activate brainpalace
   ```

2. Install packages with pinned version (bypass pip's index cache). Pin all
   three so the resolver doesn't backtrack (the conda env is Python 3.12, so the
   dashboard is always a dependency here):
   ```bash
   pip install --no-cache-dir brainpalace-rag==$VERSION brainpalace-cli==$VERSION brainpalace-dashboard==$VERSION
   ```

3. Verify:
   ```bash
   brainpalace --version
   ```

4. **Tell user:** Must run `conda activate brainpalace` before using brainpalace.

---

## Success Output

After successful installation, show:

```
BrainPalace Installation Complete
=================================

Install Method: [method user selected]
Installed Version: $VERSION
Resolved from: PyPI (latest) or (user-specified)

Next steps:
  1. Configure: /brainpalace:brainpalace-config
  2. Initialize: /brainpalace:brainpalace-init
  3. Start server: /brainpalace:brainpalace-start
```

> **What the config / init questions cover.** Both the GLOBAL `brainpalace init --global`
> (and `brainpalace install`'s own prompts; `config wizard --global` is a back-compat
> alias) and the per-project `brainpalace init` ask the **same project-config-backed question set**: embedding, summarizer,
> **reranker**, **embed-sessions** (`session_indexing.enabled` — billable opt-in,
> default OFF), **session-archive** (`session_indexing.archive.enabled` — free
> local backup of full raw transcripts incl. secrets, default ON), **git-history**
> (default OFF), and **doc-graph + session extraction engine**
> (`extraction.mode` = `off` | `subagent` | `auto` | `provider`). `init`
> re-asks the per-project-overridable **reranker** (`reranker.enabled`) behind
> an *"inherited from global — change for this project? [y/N]"* gate;
> embedding/summarizer are not re-asked via that gate (they resolve via
> env-detection / global inheritance).

> **Opt-in optional-dep rule.** Enabling a feature whose "yes" needs an optional
> server extra triggers a download — **auto-installed on yes** using the package
> manager detected here (pipx → uv → pip), or the **exact install command is
> printed** if none is detected. `extraction.mode: subagent` is free (Claude Code
> Haiku, no extra dep); `provider`/`auto` use your configured summarization
> provider (BILLABLE, also needs `EXTRACTION_PROVIDER_ENABLED=true`). Optional
> extras: BM25 `lemma` engine → `simplemma`; postgres backend → `asyncpg` +
> `sqlalchemy`. `brainpalace doctor` reports optional-extra status for enabled
> features.

---

## Why Ask First?

Different methods have different trade-offs:

| Method | Global? | Isolated? | Needs Activation? |
|--------|---------|-----------|-------------------|
| pipx | Yes | Yes | No |
| uv | Yes | Yes | No |
| pip (venv) | No | Yes | Yes |
| conda | No | Yes | Yes |

- **pipx/uv**: Best for CLI tools - globally available, no activation
- **pip (venv)**: Best for project-specific installs
- **conda**: Best for data science users already using conda
