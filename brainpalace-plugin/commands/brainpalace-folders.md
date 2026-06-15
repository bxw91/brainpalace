---
name: brainpalace-folders
description: Manage indexed folders — list, add, or remove
parameters:
skills:
  - using-brainpalace
last_validated: 2026-06-15
---

# Manage Indexed Folders

## Purpose

List, add, or remove folders from the BrainPalace index. Use this to inspect
which folders are currently indexed, trigger indexing for new folders, or
remove all chunks associated with a folder.

## Usage

```
/brainpalace:brainpalace-folders list
/brainpalace:brainpalace-folders add <path>
/brainpalace:brainpalace-folders remove <path>
/brainpalace:brainpalace-folders prune
```

`prune` removes indexed-folder records whose path no longer exists on disk.

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| action | Yes | - | list, add, remove, or prune |
| path | For add/remove | - | Path to the folder |
| --yes | No | false | Skip confirmation for remove |
| --include-code | No | true (ON) | Include code files (for add); use --no-code for doc-only |
| --include-type | No | - | File type presets, e.g., python,docs (for add) |
| --chunk-size | No | 512 | Target chunk size in tokens (for add) |
| --force | No | false | Force re-indexing, bypass manifest (for add) |
| --watch | No | auto | Watch mode: `auto` (file watching) or `off` (for add) |
| --debounce | No | 30 | Debounce interval in seconds for file watching (for add) |
| --language | No | project default (`bm25.language`) | Set the project default BM25 language (ISO 639-1, e.g. `en`, `de`, `fr`). Writes `bm25.language` to the project config. There is no per-folder language; this sets the project-wide default. |
| --json | No | false | Output as JSON (for list, add, remove) |

### Examples

```
/brainpalace:brainpalace-folders list
/brainpalace:brainpalace-folders add ./docs
/brainpalace:brainpalace-folders add ./src --include-code
/brainpalace:brainpalace-folders add ./src --include-type python,docs
/brainpalace:brainpalace-folders add ./docs --force
/brainpalace:brainpalace-folders add ./src --watch auto --debounce 10
/brainpalace:brainpalace-folders add ./docs --language de
/brainpalace:brainpalace-folders remove ./old-docs
/brainpalace:brainpalace-folders remove ./old-docs --yes
```

## Execution

Based on the action parameter:

### List Folders

Show all indexed folders with chunk counts and last indexed timestamps:

```bash
brainpalace folders list
```

### Add Folder (triggers indexing)

Queue an indexing job for the specified folder. Add supports all index options:

```bash
brainpalace folders add <path>
brainpalace folders add <path> --include-code
brainpalace folders add <path> --include-type python,docs
brainpalace folders add <path> --include-code --force

# Set the project default BM25 language (project-wide, not per-folder)
brainpalace folders add <path> --language de
brainpalace folders add <path> --language fr --include-type docs
```

**Note on `--language`**: There is no per-folder BM25 language; `--language` writes `bm25.language` to the project config as the project-wide default. All folders use the same BM25 language. To change it, run `folders add` with a new `--language` value and then re-index (or restart the server — the BM25 index auto-rebuilds from the stored corpus when the language/engine changes).

Note: `folders add` is an alias for `index` — re-adding an already-indexed folder triggers incremental re-indexing (only changed files processed).

### Remove Folder (deletes the folder's unique chunks)

Remove the folder from the index, deleting the chunks unique to it. Chunks also
referenced by another registered folder (e.g. an overlapping/nested folder) are
retained so the other folder keeps working; truly-orphaned chunks are swept by
the server's startup reconcile pass. Requires confirmation unless `--yes` is
passed:

```bash
brainpalace folders remove <path> --yes
```

### Expected Output

**List:**
```
Folder Path              Chunks  Last Indexed          Watch
/home/dev/docs          312     2026-02-24T12:00:00   off
/home/dev/src           1024    2026-02-24T13:30:00   auto
```

**Add:**
```
Indexing job queued!

Job ID: abc123
Folder: /home/dev/docs
Status: queued

Use 'brainpalace jobs' to monitor progress.
```

**Remove:**
```
Removed 312 chunks for /home/dev/docs
```

## Output

Report the results clearly:

1. **List** — Show table of indexed folders, chunk counts, and timestamps
2. **Add** — Show job ID and status; remind user to monitor with `brainpalace jobs`
3. **Remove** — Confirm number of chunks deleted

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| Server not running | BrainPalace server is stopped | Run `brainpalace start` |
| Folder not found | Folder path not indexed | Check `brainpalace folders list` |
| Active job conflict | Indexing job running for folder | Wait or cancel with `brainpalace jobs JOB_ID --cancel` |
| Connection error | Server unreachable | Verify server with `brainpalace status` |

### Recovery Commands

```bash
# Verify server is running
brainpalace status

# Check indexed folders
brainpalace folders list

# Monitor job queue
brainpalace jobs --watch
```

## Notes

- Folder paths are resolved to absolute paths automatically
- Remove does not require the folder to exist on disk
- Add is idempotent — re-indexing an already-indexed folder updates its chunks
- Use `brainpalace types list` to see available file type presets for filtering
