---
name: brainpalace-status
description: Show BrainPalace server status (health, documents, cache, watcher)
parameters:
  - name: url
    type: text
    required: false
    default: ""
  - name: json
    type: bool
    required: false
    default: false
  - name: verbose
    type: bool
    required: false
    default: false
  - name: all
    type: bool
    required: false
    default: false
skills:
  - using-brainpalace
last_validated: 2026-06-19
---

# BrainPalace Status

## Purpose

Displays the current status of the BrainPalace server, including:
- Server health and version
- Document and chunk counts
- Indexing progress (if in progress)
- Indexed folders list
- File watcher status
- Embedding cache statistics
- Graph index status (if enabled)

Use this command to verify the server is running before performing searches.

## Usage

```
/brainpalace:brainpalace-status [--url <url>] [--json] [--verbose]
```

### Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| --url | No | from config or http://127.0.0.1:8000 | Server URL (env: BRAINPALACE_URL) |
| --json | No | false | Output in JSON format for scripting |
| --verbose, -v | No | false | Show additional detail (cache size, memory stats) |
| --all, -a | No | false | Show detailed status for every running registered server |

## Execution

### Basic Status Check

```bash
brainpalace status
```

### Verbose Status

```bash
brainpalace status --verbose
```

### JSON Output

```bash
brainpalace status --json
```

## Output

### Human-Readable Format

```
          Server Status
           HEALTHY

Metric             Value
Server Version     9.0.0
Total Documents    142
Total Chunks       750
Indexing           Idle
Indexed Folders    ./docs
                   ./src
File Watcher       running (2 watched folder(s))
Embedding Cache    1,200 entries, 85.3% hit rate (1,024 hits, 176 misses)
Graph Index        Enabled - 45 entities, 120 rels
BM25 Language      en (engine: stem)
```

### JSON Format

```json
{
  "health": {
    "status": "healthy",
    "message": "Server is running",
    "version": "9.0.0"
  },
  "indexing": {
    "total_documents": 142,
    "total_chunks": 750,
    "indexing_in_progress": false,
    "progress_percent": 0.0,
    "indexed_folders": ["./docs", "./src"],
    "file_watcher": {
      "running": true,
      "watched_folders": 2
    },
    "embedding_cache": {
      "entry_count": 1200,
      "hit_rate": 0.853,
      "hits": 1024,
      "misses": 176
    }
  },
  "bm25": {
    "language": "en",
    "engine": "stem"
  }
}
```

### Status Indicators

| Status | Meaning |
|--------|---------|
| `healthy` | Server running and responsive |
| `unhealthy` | Server running but issues detected |
| `not_running` | Server not started |
| `indexing` | Currently indexing documents |
| `idle` | Ready for queries |

## Error Handling

### Server Not Running

```
Error: BrainPalace server is not running

To start the server:
  brainpalace start
```

**Resolution**: Start the server:
```bash
brainpalace start
```

### Connection Refused

```
Error: Could not connect to server at http://127.0.0.1:8000
Connection refused
```

**Resolution**:
1. Check if server is running: `ps aux | grep brainpalace`
2. Start the server: `brainpalace start`
3. Check if port is blocked by firewall

### Runtime File Missing

```
Warning: No runtime.json found
Using default URL: http://127.0.0.1:8000
```

**Resolution**: Initialize the project:
```bash
brainpalace init
brainpalace start
```

### Health Check Failed

```
Status: unhealthy

Issues detected:
  - Vector DB: connection failed
  - BM25 Index: not initialized
```

**Resolution**:
1. Check ChromaDB is accessible
2. Re-index documents: `brainpalace index /path/to/docs`
3. Restart server: `brainpalace stop && brainpalace start`

## Use Cases

### Before Searching

Always check status before performing searches:

```bash
# Check server is ready
brainpalace status

# If healthy and documents indexed, proceed with search
brainpalace query "search term" --mode hybrid
```

### Troubleshooting

Use JSON output for scripting and diagnostics:

```bash
# Check document count
brainpalace status --json | jq '.indexing.total_documents'

# Check health status
brainpalace status --json | jq -r '.health.status'
```

### CI/CD Integration

```bash
# Wait for server to be healthy
until brainpalace status --json | jq -e '.health.status == "healthy"'; do
  sleep 1
done
```

## Related Commands

| Command | Description |
|---------|-------------|
| `/brainpalace:brainpalace-start` | Start the server |
| `/brainpalace:brainpalace-stop` | Stop the server |
| `/brainpalace:brainpalace-list` | List all running instances |

### Flags
<!--GENERATED:flags-->
| Flag | Type | Default | Description |
|------|------|---------|-------------|
| --url | text | "" | BrainPalace server URL (default: from config or http://127.0.0.1:8000) |
| --json | bool | false | Output as JSON |
| --verbose | bool | false | Show additional detail |
| --all | bool | false | Show detailed status for every running registered server |
<!--/GENERATED-->
