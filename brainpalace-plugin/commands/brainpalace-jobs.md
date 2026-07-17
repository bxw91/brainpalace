---
name: brainpalace-jobs
description: Monitor and manage async indexing jobs in the queue
parameters:
  - name: watch
    type: bool
    required: false
    default: false
  - name: cancel
    type: bool
    required: false
    default: false
  - name: approve
    type: bool
    required: false
    default: false
  - name: limit
    type: integer
    required: false
    default: 20
  - name: all
    type: bool
    required: false
    default: false
  - name: url
    type: text
    required: false
    default: ""
  - name: json
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-07-17
---

# Job Queue Management

## Purpose

Monitor and manage async indexing jobs. Indexing runs in the background via a job queue — use this command to list jobs, watch progress, inspect details (including eviction summaries for incremental indexing), and cancel stuck or unwanted jobs.

## Usage

```
/brainpalace:brainpalace-jobs
/brainpalace:brainpalace-jobs --watch
/brainpalace:brainpalace-jobs <job_id>
/brainpalace:brainpalace-jobs <job_id> --cancel
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| job_id | No | - | Specific job ID to inspect |
| --watch / -w | No | false | Poll queue every 3 seconds with live updates |
| --cancel / -c | No | false | Cancel the specified job (requires job_id) |
| --limit / -l | No | 20 | Maximum number of jobs to show |
| --json | No | false | Output as JSON |

### Examples

```
# List all jobs
/brainpalace:brainpalace-jobs

# Watch queue with live updates
/brainpalace:brainpalace-jobs --watch

# Inspect a specific job
/brainpalace:brainpalace-jobs abc123

# Cancel a running job
/brainpalace:brainpalace-jobs abc123 --cancel
```

## Execution

Based on the parameters:

### List All Jobs

```bash
brainpalace jobs
```

### Watch Queue (Live Updates)

```bash
brainpalace jobs --watch
```

Press Ctrl+C to stop watching.

### Inspect Job Details

```bash
brainpalace jobs <job_id>
```

### Cancel a Job

```bash
brainpalace jobs <job_id> --cancel
```

### Expected Output

**List:**
```
Job ID    Status     Folder                  Created
abc123    done       /home/dev/docs         2026-03-05T12:00:00
def456    running    /home/dev/src          2026-03-05T12:05:00
ghi789    pending    /home/dev/tests        2026-03-05T12:06:00
```

**Job Detail (with eviction summary):**
```
Job Details: abc123

Status:    done
Folder:    /home/dev/docs
Created:   2026-03-05T12:00:00
Completed: 2026-03-05T12:00:45

Eviction Summary:
  Files added:     3
  Files changed:   2
  Files deleted:   1
  Files unchanged: 42
  Chunks evicted:  15
  Chunks created:  25
```

**Watch mode:**
```
Job Queue (polling every 3s, Ctrl+C to stop)

Job ID    Status     Folder                  Progress
def456    running    /home/dev/src          Processing...
ghi789    pending    /home/dev/tests        Waiting...
```

## Job Status Values

| Status | Meaning |
|--------|---------|
| `pending` | Job is queued, waiting to start |
| `running` | Job is actively indexing |
| `done` | Job finished successfully |
| `failed` | Job encountered an error |
| `cancelled` | Job was cancelled by user |
| `skipped` | Job was skipped (no work needed) |

## Eviction Summary (Incremental Indexing)

When a folder is re-indexed, BrainPalace uses manifest tracking to detect changes. The eviction summary shows:

| Field | Meaning |
|-------|---------|
| Files added | New files not previously indexed |
| Files changed | Files with different content (old chunks evicted, new ones created) |
| Files deleted | Files removed from disk (their chunks are evicted) |
| Files unchanged | Files with same content (skipped for efficiency) |
| Chunks evicted | Old chunk embeddings removed from the index |
| Chunks created | New chunk embeddings added to the index |

This enables efficient incremental updates — only changed files are re-processed.

## Error Handling

| Error | Cause | Resolution |
|-------|-------|------------|
| Server not running | BrainPalace server is stopped | Run `brainpalace start` |
| Job not found | Invalid job ID | Check `brainpalace jobs` for valid IDs |
| Queue full (429) | Too many concurrent jobs | Wait for current jobs to complete |
| Connection error | Server unreachable | Verify with `brainpalace status` |

### Recovery Commands

```bash
# Check server status
brainpalace status

# List all jobs to find valid IDs
brainpalace jobs

# Cancel a stuck job
brainpalace jobs <job_id> --cancel

# Force re-index if job failed
brainpalace index <path> --force
```

## Notes

- Jobs run asynchronously in the background
- Only one job runs at a time; others queue in FIFO order
- Watch mode polls every 3 seconds and shows live status changes
- Eviction summary only appears for incremental re-indexing (not first-time indexing)
- Use `--force` on the index/inject command to bypass manifest and force full re-indexing
- Job history persists across server restarts (JSONL storage)

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --watch | bool | false | Poll every 3 seconds |
| --cancel | bool | false | Cancel the specified job |
| --approve | bool | false | Approve a budget-blocked job (spends embedding tokens) |
| --limit | integer | 20 | Max jobs to show (default: 20) |
| --all | bool | false | Include no-op completed jobs (status=done, no chunk delta, no error) that are hidden by default |
| --url | text | "" | BrainPalace server URL (default: from config or http://127.0.0.1:8000) |
| --json | bool | false | Output as JSON |
<!--/GENERATED-->
