---
name: brainpalace-verify
description: Verify BrainPalace installation and configuration
parameters: []
context: brainpalace
agent: setup-assistant
skills:
  - configuring-brainpalace
last_validated: 2026-07-21
---

# Verify BrainPalace Setup

## Purpose

Performs a comprehensive verification of the BrainPalace installation, checking that all components are properly installed, configured, and functioning. This is a plugin-level workflow that runs multiple CLI commands to produce a consolidated health check report.

## Usage

```
/brainpalace:brainpalace-verify
```

## Execution

Run the following verification steps in sequence:

### Step 1: Check Package Installation

```bash
brainpalace --version
python -c "import brainpalace_cli; print(brainpalace_cli.__version__)" 2>/dev/null
python -c "import brainpalace_server; print(brainpalace_server.__version__)" 2>/dev/null
```

### Step 2: Check Python Version

```bash
python --version
```

### Step 3: Check Provider Configuration

```bash
# Show active provider config
brainpalace config show 2>/dev/null || echo "Config not available"
```

### Step 4: Check Project Initialization

`.brainpalace/config.yaml` holds both the **project settings** written by
`brainpalace init` and the **provider settings** (embedding/summarization) in
one file. It is expected in an initialized project.

```bash
ls -la .brainpalace/config.yaml 2>/dev/null
```

### Step 5: Check Server Status (if running)

```bash
brainpalace status
```

### Step 6: Run Health Check (if server running)

```bash
brainpalace status --json 2>/dev/null || echo "Server not running"
```

## Output

### All Checks Passing

```
BrainPalace Verification
========================

Installation
------------
[OK] brainpalace-cli: 1.2.0
[OK] brainpalace-rag: 1.2.0
[OK] Python: 3.11.4 (>= 3.10 required)

Configuration
-------------
[OK] OPENAI_API_KEY: Set
[OK] ANTHROPIC_API_KEY: Set (optional)

Project Setup
-------------
[OK] Project initialized: .brainpalace/
[OK] Config file: .brainpalace/config.yaml (project settings)

Server Status
-------------
[OK] Server running on port 49321
[OK] Health: healthy
[OK] Documents indexed: 150
[OK] Chunks: 750

Verification Complete!
======================

All checks passed. BrainPalace is ready to use.

Quick commands:
  Search: /brainpalace:brainpalace-query "your query"
  Index:  /brainpalace:brainpalace-index /path/to/docs
  Status: /brainpalace:brainpalace-status
```

### Some Checks Failing

```
BrainPalace Verification
========================

Installation
------------
[OK] brainpalace-cli: 1.2.0
[OK] brainpalace-rag: 1.2.0
[OK] Python: 3.11.4

Configuration
-------------
[OK] OPENAI_API_KEY: Set
[--] ANTHROPIC_API_KEY: Not set (optional)

Project Setup
-------------
[!!] Project not initialized

Server Status
-------------
[!!] Server not running

Verification Summary
====================

Issues Found: 2

1. Project not initialized
   Fix: brainpalace init

2. Server not running
   Fix: brainpalace start

Run /brainpalace:brainpalace-setup to fix all issues automatically.
```

## Checklist Format

For quick reference, the verification can also output as a checklist:

```
BrainPalace Verification Checklist
===================================

Packages:
  [x] brainpalace-cli installed
  [x] brainpalace-rag installed
  [x] Python >= 3.10

API Keys:
  [x] OPENAI_API_KEY set
  [ ] ANTHROPIC_API_KEY set (optional)

Project:
  [x] .brainpalace/ exists
  [x] config.yaml present (project settings)

Server:
  [x] Server running
  [x] Health check passed
  [x] Documents indexed (150)

Status: Ready (5/6 checks passed)
```

## Error Handling

### Packages Not Installed

```
[!!] brainpalace-cli: NOT FOUND

The BrainPalace CLI is not installed.

Fix:
  pip install brainpalace-cli brainpalace-rag

Or run: /brainpalace:brainpalace-install
```

### Python Version Too Low

```
[!!] Python: 3.8.10 (requires >= 3.10)

Python 3.10 or higher is required.

Fix:
  1. Install Python 3.10+: https://python.org/downloads/
  2. Use pyenv: pyenv install 3.11
  3. Use conda: conda create -n brainpalace python=3.11
```

### API Key Not Set

```
[!!] OPENAI_API_KEY: NOT SET

The OpenAI API key is required for semantic search.

Fix:
  export OPENAI_API_KEY="sk-proj-..."

Or run: /brainpalace:brainpalace-config
```

### Project Not Initialized

```
[!!] Project not initialized

No .brainpalace/ directory found.

Fix:
  brainpalace init

Or run: /brainpalace:brainpalace-init
```

### Server Not Running

```
[!!] Server not running

The BrainPalace server is not running.

Fix:
  brainpalace start

After starting, verify with:
  brainpalace status
```

### Server Unhealthy

```
[!!] Server unhealthy

Server is running but health check failed.

Diagnostics:
  1. Check server logs
  2. Verify API key is valid
  3. Restart: brainpalace stop && brainpalace start
```

### No Documents Indexed

```
[--] Documents indexed: 0

No documents have been indexed yet.

To index documents:
  brainpalace index /path/to/docs

This is not an error, but search will return no results
until documents are indexed.
```

## Quick Fix Mode

If verification fails, suggest the automated fix:

```
Verification found 3 issues.

Quick fix: Run /brainpalace:brainpalace-setup to resolve all issues automatically.

Or fix manually:
  1. pip install brainpalace-cli brainpalace-rag
  2. export OPENAI_API_KEY="your-key"
  3. brainpalace init
  4. brainpalace start
```
