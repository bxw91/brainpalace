---
last_validated: 2026-06-15
---

# LSP Cross-References (Phase 150)

Augment the code knowledge graph with **typed cross-references from a real
language server** — calls, type hierarchies, definitions — instead of
heuristics. Opt-in, per-language, and fail-soft.

> **Status:** v11 feature. Ships disabled. The tree-sitter AST metadata graph
> (default) already covers imports/containment; LSP adds precise call/type edges
> for languages you explicitly enable and have a server installed for.

## What it adds

For each indexed code symbol, the server is queried and the results become typed
graph triplets keyed on a canonical **Symbol-Id** = `file:fqname`
(e.g. `pkg/mod.py:Handler.run`):

| Relation | Source LSP request | Meaning |
|----------|--------------------|---------|
| `calls` | `callHierarchy/incomingCalls` + `outgoingCalls` | caller → callee |
| `extends` | `typeHierarchy/supertypes` (class) | subclass → base class |
| `implements` | `typeHierarchy/supertypes` (interface) | class → interface |
| `defined-at` | `textDocument/definition` | symbol → `file:line` |

These compose with the existing GraphRAG modes (`brainpalace query -m graph` /
`multi`) and the persistent SQLite graph backend (recommended at this volume —
see [GRAPHRAG_GUIDE](GRAPHRAG_GUIDE.md#storage-backends)).

## Enabling

LSP is **inert** unless you list languages **and** install the matching server.

```bash
# 1. Install the language server(s) yourself (examples):
npm  i -g pyright                       # python
npm  i -g typescript-language-server    # typescript/javascript
go   install golang.org/x/tools/gopls@latest   # go

# 2. Allow-list the languages (comma-separated):
export BRAINPALACE_LSP_LANGUAGES="python"

# 3. Index as usual — LSP cross-refs are extracted for code chunks in those
#    languages during graph build. Requires ENABLE_GRAPH_INDEX=true.
export ENABLE_GRAPH_INDEX=true
```

| Language | id | Server command |
|----------|----|----------------|
| Python | `python` | `pyright-langserver --stdio` |
| TypeScript / JavaScript | `typescript` | `typescript-language-server --stdio` |
| Go | `go` | `gopls` |

A missing binary, an unsupported language, or a server crash yields **fewer
triplets, never an error** — indexing always completes.

## Design notes

- **Tiny client.** `brainpalace_server/lsp/client.py` is a minimal synchronous
  JSON-RPC-over-stdio client (LSP `Content-Length` framing) — no async, no LSP
  framework, no new runtime dependency.
- **Per-language, lazily spawned** servers, cached for the indexing run, shut
  down after.
- **Symbol-Id** (`models/graph.py::symbol_id`) is the join key; Phase 140's path
  canonicalisation aligns file paths to the same form.

## Limitations / roadmap

- Single-symbol-per-chunk position (uses the chunk's `start_line`); whole-file
  symbol enumeration is future work.
- `root_uri` is not yet wired from the project root into the indexing-time
  extractor — fine for single-file resolution; cross-file resolution accuracy
  improves once it is. (Tracked for a follow-up.)
- Live coverage depends on installed servers; CI runs the mocked-protocol tests
  and skips the live test when no server is present.
