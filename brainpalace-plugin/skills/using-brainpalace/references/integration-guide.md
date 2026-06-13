---
last_validated: 2026-06-13
---

# Integration Guide

Patterns for integrating BrainPalace into scripts, applications, and CI/CD pipelines.

## Contents

- [CLI Scripting](#cli-scripting)
- [Python API Integration](#python-api-integration)
- [CI/CD Integration](#cicd-integration)
- [Multi-Project Workflow](#multi-project-workflow)

---

## CLI Scripting

```bash
# Basic query with JSON output
RESULT=$(brainpalace query "$QUERY" --mode hybrid --json)
echo "$RESULT" | jq '.results[0].text'

# Check if results found
if brainpalace query "search term" --mode bm25 --threshold 0.1 > /dev/null 2>&1; then
    echo "Found matching documents"
fi

# Iterate over results
brainpalace query "error handling" --json | jq -r '.results[].source'
```

---

## Python API Integration

```python
import json
import subprocess
from pathlib import Path
import requests

def get_server_url():
    """Get server URL from runtime.json or default."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, check=True
        )
        project_root = Path(result.stdout.strip())
        runtime_path = project_root / ".brainpalace" / "runtime.json"
        if runtime_path.exists():
            state = json.loads(runtime_path.read_text())
            return state.get("base_url", "http://localhost:8000")
    except Exception:
        pass
    return "http://localhost:8000"


def query_docs(query: str, mode: str = "hybrid", top_k: int = 5) -> list:
    """Query BrainPalace and return results."""
    server_url = get_server_url()
    response = requests.post(
        f'{server_url}/query/',
        json={'query': query, 'mode': mode, 'top_k': top_k}
    )
    response.raise_for_status()
    return response.json().get('results', [])


# Usage
results = query_docs("authentication guide", mode="hybrid")
for r in results:
    print(f"{r['source']}: {r['score']:.2f}")
```

---

## CI/CD Integration

```bash
#!/bin/bash
# Documentation validation in CI pipeline

set -e

# Initialize and start server
brainpalace init
brainpalace start

# Wait for server readiness
for i in {1..10}; do
    if brainpalace status > /dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Index documentation
brainpalace index ./docs

# Run validation queries
echo "Checking for deprecated features..."
if brainpalace query "deprecated" --mode bm25 --threshold 0.1 --json | jq -e '.total_results > 0' > /dev/null; then
    echo "Warning: Found deprecated content"
fi

echo "Verifying API documentation..."
brainpalace query "API endpoint" --mode hybrid --threshold 0.5

# Cleanup
brainpalace stop

echo "Documentation validation complete"
```

---

## Multi-Project Workflow

```bash
# Work with multiple projects simultaneously
cd /project-a && brainpalace start  # Auto-port (e.g., 54321)
cd /project-b && brainpalace start  # Different port (e.g., 54322)

# List all running instances
brainpalace list
# Instance   Project          Port   Status
# a1b2c3d4   /project-a       54321  running
# e5f6g7h8   /project-b       54322  running

# Query specific project (from its directory)
cd /project-a && brainpalace query "auth module"
cd /project-b && brainpalace query "database schema"

# Cleanup
cd /project-a && brainpalace stop
cd /project-b && brainpalace stop
```

---

## Additional Integration Patterns

### File Watcher Integration (v8.0+)

Enable auto-reindex for continuous integration workflows:

```bash
# Enable file watcher on source directory
brainpalace folders add ./src --watch auto --include-code --debounce 10

# Monitor auto-triggered jobs
brainpalace jobs --watch
```

### Embedding Cache Integration (v8.0+)

The embedding cache automatically stores computed embeddings to avoid redundant
API calls during reindexing. It is active by default — no setup required.
Unchanged content (identified by SHA-256 hash) reuses cached vectors on reindex,
complementing the ManifestTracker.

Monitor cache health in CI pipelines:

```bash
# Check cache hit rate
brainpalace cache status --json | jq '.hit_rate'

# Clear cache if switching providers
brainpalace cache clear --yes
```

**When to check cache status:**
- After indexing — verify the cache works and hit rate is growing
- When queries seem slow — a low/zero hit rate means embeddings are recomputed every reindex
- To monitor cache growth — track disk usage over time for large indexes

A healthy cache shows a hit rate > 80% after the first full reindex cycle,
growing disk entries over time, and low misses relative to hits.

**When to clear the cache:**
- After changing embedding provider or model — prevents dimension mismatches and stale vectors
- Suspected cache corruption — if search quality degrades unexpectedly
- To force fresh embeddings — when all vectors must reflect the current provider/model

See `references/api_reference.md` for the `GET /index/cache` and
`DELETE /index/cache` endpoint schemas.

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BRAINPALACE_URL` | Override server URL | Auto-discovered |
| `DOC_SERVE_URL` | Legacy override (still supported) | Auto-discovered |
| `OPENAI_API_KEY` | Required for vector/hybrid modes | - |
| `ANTHROPIC_API_KEY` | Optional for summarization | - |
