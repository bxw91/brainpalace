---
last_validated: 2026-06-20
---

# Troubleshooting Guide

## Overview

This guide covers common issues and their solutions when using BrainPalace for document indexing and search.

## Common Problems and Solutions

### 1. Server Won't Start

**Symptoms:**
- `brainpalace-serve` command fails to start
- Error messages about missing modules or imports
- Port already in use errors

**Solutions:**

**Module Import Errors:**
```bash
# Reinstall global CLI tools
pip install brainpalace-rag brainpalace-cli

# Or run locally
cd brainpalace-server && poetry run brainpalace-serve
```

**Port Already in Use:**
```bash
# Find what's using port 8000
lsof -i :8000

# Kill the process
kill -9 <PID>

# Or use different port
brainpalace-serve --port 8001
```

**Permission Errors:**
```bash
# Check if you can write to the directory
ls -la brainpalace-server/
chmod 755 brainpalace-server/
```

### 2. Missing OpenAI API Key

**Symptoms:**
- Hybrid/vector queries fail with authentication errors
- Error: "No API key found for OpenAI"
- BM25 works but hybrid/vector don't

**Solutions:**

**Set API Key in .env file:**
```bash
cd brainpalace-server
echo "OPENAI_API_KEY=sk-your-key-here" > .env
echo "ANTHROPIC_API_KEY=sk-ant-your-key-here" >> .env
```

**Set as Environment Variables:**
```bash
export OPENAI_API_KEY="sk-your-key-here"
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
brainpalace-serve
```

**Get API Keys:**
- OpenAI: https://platform.openai.com/account/api-keys
- Anthropic: https://console.anthropic.com/

**Verify Key Format:**
```bash
# Should start with sk-proj or sk-
echo $OPENAI_API_KEY | head -c 15
```

### 3. Missing Anthropic API Key

**Symptoms:**
- Some summarization features fail
- Warnings about missing Anthropic key
- Core search still works

**Solutions:**

**Add to .env file:**
```bash
cd brainpalace-server
echo "ANTHROPIC_API_KEY=sk-ant-your-key-here" >> .env
```

**Get API Key:**
- Anthropic: https://console.anthropic.com/

**Note:** Anthropic key is optional for basic search functionality.

### 4. No Documents Indexed

**Symptoms:**
- `brainpalace status` shows 0 documents
- All queries return empty results
- Indexing seems to complete but no data

**Solutions:**

**Check if indexing ran:**
```bash
brainpalace status
# Should show: Total Documents: > 0
```

**Run indexing:**
```bash
brainpalace index /path/to/your/docs
# Wait for completion message
```

**Verify document path:**
```bash
ls -la /path/to/your/docs
# Should contain .md, .txt, .pdf files
```

**Check supported formats:**
- ✅ Markdown (.md)
- ✅ Text (.txt)
- ✅ PDF (.pdf)
- ❌ Word docs, images (not supported)

### 5. BM25 Index Not Ready

**Symptoms:**
- BM25 queries fail with "BM25 index not initialized"
- Hybrid queries fail but vector works
- Status shows BM25 index missing

**Solutions:**

**Wait for indexing to complete:**
```bash
brainpalace status
# Wait until indexing shows "Idle"
```

**Re-index if needed:**
```bash
brainpalace reset --yes
brainpalace index /path/to/docs
```

**Check server logs:**
```bash
# Look for BM25 indexing messages
tail -f server.log
```

### 6. No Search Results Found

**Symptoms:**
- Queries return empty results array
- Server is running and documents are indexed

**Solutions:**

**Lower threshold:**
```bash
# Default is 0.3, try lower values
brainpalace query "your search" --threshold 0.1
```

**Check query spelling:**
```bash
# Try variations of your query
brainpalace query "alternative wording"
```

**Use different search modes:**
```bash
# Try BM25 for exact matches
brainpalace query "exact term" --mode bm25 --threshold 0.1

# Try vector for semantic search
brainpalace query "conceptual description" --mode vector --threshold 0.5
```

**Verify content exists:**
```bash
# Search for common words
brainpalace query "the" --mode bm25 --threshold 0.01
```

### 7. Slow Query Performance

**Symptoms:**
- Queries take longer than expected
- Hybrid/vector queries are slow (>2 seconds)

**Solutions:**

**Use BM25 for speed:**
```bash
# Fastest option, no API calls
brainpalace query "exact terms" --mode bm25
```

**Optimize hybrid settings:**
```bash
# Reduce top-k for faster results
brainpalace query "search" --top-k 3 --alpha 0.5
```

**Check network connectivity:**
```bash
# Test OpenAI API connectivity
curl -H "Authorization: Bearer $OPENAI_API_KEY" https://api.openai.com/v1/models
```

**Monitor server resources:**
```bash
# Check if server is overloaded
top -p $(pgrep -f "brainpalace")
```

### 8. Connection Refused Errors

**Symptoms:**
- `brainpalace` commands fail with connection errors
- "Unable to connect to server" messages

**Solutions:**

**Start the server (multi-instance mode):**
```bash
brainpalace start   # Uses auto-port allocation
brainpalace status           # Shows the actual port
```

**Check server status:**
```bash
brainpalace status
# Should show server is healthy with port number
```

**Verify port from runtime.json:**
```bash
# Check what port was assigned
cat .brainpalace/runtime.json | jq '.port'
```

**List all running instances:**
```bash
brainpalace list
# Shows all projects with their ports
```

**Use correct URL:**
```bash
# Override URL if needed
export BRAINPALACE_URL="http://localhost:54321"
brainpalace status
```

### 8. PostgreSQL Backend Issues

**Connection refused (PostgreSQL):**

- Confirm the container is running:
```bash
docker compose -f docker-compose.postgres.yml ps
```
- Check readiness:
```bash
docker compose -f docker-compose.postgres.yml exec postgres \
  pg_isready -U brainpalace -d brainpalace
```

**pgvector extension missing:**

- Use the pgvector image (`pgvector/pgvector:pg16`).
- If using another image, install the pgvector extension before start.

**Pool exhaustion / too many connections:**

- Increase `pool_size` and `pool_max_overflow` under `storage.postgres`.
- Ensure PostgreSQL `max_connections` is high enough for your workload.

**Embedding dimension mismatch:**

- If you change embedding models, reset and re-index:
```bash
brainpalace reset --yes
brainpalace index /path/to/docs
```

### 8a. Stale Server State (Multi-Instance)

**Symptoms:**
- `runtime.json` exists but server is not responding
- "Server not responding" warnings
- Previous server crashed without cleanup

**Solutions:**

**Let the CLI handle it:**
```bash
# CLI automatically detects stale state and starts fresh
brainpalace start
```

**Manual cleanup:**
```bash
# Remove stale state files
rm .brainpalace/runtime.json
rm .brainpalace/lock.json
rm .brainpalace/pid

# Start fresh
brainpalace start
```

### 8b. Multiple Agents Racing to Start

**Symptoms:**
- "Another instance is already running" error
- Lock acquisition failures

**Solutions:**

The lock file protocol prevents double-start automatically:
```bash
# First agent wins and starts the server
# Second agent should detect the running instance
brainpalace status

# If lock is stale (process died), cleanup happens automatically
brainpalace start
```

**If locks persist incorrectly:**
```bash
# Manual lock cleanup (only if process is truly dead)
ps aux | grep brainpalace  # Verify no process running
rm .brainpalace/lock.json
brainpalace start
```

### 9. Invalid API Key Errors

**Symptoms:**
- Authentication failed messages
- 401 Unauthorized responses
- Works with BM25 but fails with hybrid/vector

**Solutions:**

**Check API key validity:**
```bash
# Test OpenAI key
curl https://api.openai.com/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY" \
  -H "Content-Type: application/json"
```

**Verify key format:**
```bash
# Should be sk-proj-... or sk-...
echo $OPENAI_API_KEY | grep -E "^sk-(proj-)?[a-zA-Z0-9]"
```

**Check account credits:**
- OpenAI: https://platform.openai.com/account/usage
- Ensure account has credits and API access

**Regenerate key if needed:**
- OpenAI: https://platform.openai.com/account/api-keys
- Delete old key, create new one

### 10. Memory or Resource Issues

**Symptoms:**
- Server crashes with out of memory errors
- Queries fail with resource exhaustion
- System becomes unresponsive

**Solutions:**

**Reduce batch sizes:**
```bash
# Smaller embedding batches
export EMBEDDING_BATCH_SIZE=50
```

**Limit concurrent requests:**
```bash
# Use single-threaded mode if needed
export WEB_CONCURRENCY=1
```

**Monitor resource usage:**
```bash
# Check memory usage
ps aux | grep brainpalace
top -p $(pgrep -f "brainpalace")
```

**Restart with clean state:**
```bash
brainpalace reset --yes
brainpalace index /path/to/docs
```

### 11. JSON Parsing Errors

**Symptoms:**
- `--json` output is malformed
- Parsing errors in scripts
- Unexpected response format

**Solutions:**

**Check API response:**
```bash
curl -s http://localhost:8000/health | python -m json.tool
```

**Validate JSON output:**
```bash
brainpalace query "test" --json | jq .
```

**Update CLI version:**
```bash
pip install brainpalace-rag brainpalace-cli
```

### 12. File Permission Issues

**Symptoms:**
- Cannot read documents during indexing
- Cannot write index files
- Permission denied errors

**Solutions:**

**Check file permissions:**
```bash
ls -la /path/to/docs
chmod 644 /path/to/docs/*.md
```

**Check index directory permissions:**
```bash
ls -la brainpalace-server/
chmod 755 brainpalace-server/
mkdir -p brainpalace-server/chroma_db
chmod 755 brainpalace-server/chroma_db
```

**Run as appropriate user:**
```bash
# Don't run as root unless necessary
whoami
```

## Diagnostic Commands

### Check System Status
```bash
# Server health
brainpalace status

# Check API connectivity
curl http://localhost:8000/health

# Test basic query
brainpalace query "test" --mode bm25
```

### Check Environment
```bash
# API keys set
echo "OpenAI: ${OPENAI_API_KEY:+SET}"
echo "Anthropic: ${ANTHROPIC_API_KEY:+SET}"

# Python environment
which python
python --version

# Poetry environment
cd brainpalace-server && poetry env info
```

### Check Logs
```bash
# Server logs
tail -f server.log

# System logs
dmesg | tail -20

# Network connectivity
ping -c 3 api.openai.com
```

## Getting Help

If these solutions don't resolve your issue:

1. **Check GitHub Issues**: https://github.com/bxw91/brainpalace/issues
2. **Provide diagnostic info**: Run the diagnostic commands above
3. **Include error messages**: Copy full error output
4. **Describe your setup**: OS, Python version, installation method

## File Watcher Issues (v8.0+)

### Watcher Not Triggering Re-index

**Symptoms:**
- Edited files not automatically re-indexed
- No auto-triggered jobs in `brainpalace jobs`

**Solutions:**

```bash
# Verify watch mode is enabled on folder
brainpalace folders list

# Enable watching
brainpalace folders add ./src --watch auto --include-code

# Lower debounce for faster response (default 30s)
brainpalace folders add ./src --watch auto --debounce 10
```

**Excluded directories:** `.git/`, `node_modules/`, `__pycache__/`, `dist/`, `build/`, `.next/`, `.nuxt/`, `coverage/`, `htmlcov/`

---

## Embedding Cache Issues (v8.0+)

### Low Hit Rate or Slow Re-indexing

```bash
# Check cache health
brainpalace cache status

# If you changed embedding provider, clear old cached embeddings
brainpalace cache clear --yes

# Re-index to rebuild cache
brainpalace index /path/to/docs
```

**Configuration:** `EMBEDDING_CACHE_MAX_DISK_MB` (default: 500MB), `EMBEDDING_CACHE_MAX_MEM_ENTRIES` (default: 10000)

---

## Multi-Runtime Install Issues (v9.0+)

### Plugin Not Found After Install

```bash
# Verify plugin was installed
ls .claude/plugins/brainpalace/  # For Claude
ls .opencode/plugins/brainpalace/  # For OpenCode

# Re-install
brainpalace install-agent --agent claude

# Preview what will be installed
brainpalace install-agent --agent claude --dry-run
```

---

## Prevention Tips

- Always run `task pr-qa-gate` before committing changes
- Keep API keys secure and don't commit them
- Use environment variables for sensitive configuration
- Regularly update dependencies with `poetry update`
- Monitor server logs for early warning signs
- Test with different search modes when queries fail
- Use `brainpalace cache status` to monitor embedding cache health
- Enable file watcher (`--watch auto`) for automatic re-indexing
