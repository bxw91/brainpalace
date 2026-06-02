---
last_validated: 2026-05-30
---

# Deployment Guide

This guide covers deploying BrainPalace in various environments, from local development to production deployments.

## Table of Contents

- [Local Development](#local-development)
- [Production Considerations](#production-considerations)
- [Docker Deployment](#docker-deployment)
- [Resource Requirements](#resource-requirements)
- [Monitoring and Observability](#monitoring-and-observability)
- [Security Considerations](#security-considerations)
- [Troubleshooting](#troubleshooting)

---

## Local Development

### Quick Start

```bash
# 1. Install the CLI + server (pipx installs brainpalace-cli, which pulls brainpalace-rag)
curl -sSL https://raw.githubusercontent.com/bxw91/brainpalace/main/scripts/install.sh | bash

# 2. Set API keys
export OPENAI_API_KEY="sk-proj-..."
export ANTHROPIC_API_KEY="sk-ant-..."  # Optional

# 3. Initialize project
cd /path/to/your/project
brainpalace init

# 4. Start server
brainpalace start --daemon

# 5. Index documents
brainpalace index ./docs

# 6. Verify
brainpalace status
```

### Optional: MCP transport for non-Claude-Code clients

To expose BrainPalace to **MCP-aware AI clients** (VS Code native / GitHub
Copilot agent mode, Cursor, Kilo Code, Cline, Continue, Zed) add an MCP
entry to the client's config pointing at `brainpalace mcp --ensure-server`.
The client spawns the shim as a child process over stdio — there is no extra
server to deploy and no extra port to open. Lifecycle is owned by the
client (one MCP process per workspace, reaped on disconnect). See
[`MCP_SETUP.md`](MCP_SETUP.md) for per-client snippets and the VS Code
PATH-inheritance gotcha.

### Development Server Options

```bash
# Start with auto-reload for development
brainpalace start --reload

# Start with debug logging
DEBUG=true brainpalace start

# Start on specific port
brainpalace start --port 8080

# Start in foreground (see logs)
brainpalace start
```

### Virtual Environment Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# or
.venv\Scripts\activate     # Windows

# Install from PyPI
pip install --upgrade brainpalace-cli

# Verify installation
brainpalace --version
brainpalace-serve --version
```

---

## Production Considerations

### Checklist

Before deploying to production:

- [ ] API keys stored securely (environment variables or secrets manager)
- [ ] Storage paths point to persistent volumes
- [ ] Appropriate resource limits configured
- [ ] Health endpoints monitored
- [ ] Backup strategy for indexed data
- [ ] Security: bind to localhost or use reverse proxy

### Environment Configuration

Create a production `.env` file:

```bash
# Required
OPENAI_API_KEY=sk-proj-...

# Optional (for GraphRAG)
ANTHROPIC_API_KEY=sk-ant-...

# Server Configuration
API_HOST=127.0.0.1
API_PORT=8000
DEBUG=false

# Embedding
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_DIMENSIONS=3072

# Storage - point to persistent volumes
CHROMA_PERSIST_DIR=/data/brainpalace/vectors
BM25_INDEX_PATH=/data/brainpalace/bm25

# GraphRAG (optional)
ENABLE_GRAPH_INDEX=true
GRAPH_STORE_TYPE=simple
GRAPH_INDEX_PATH=/data/brainpalace/graph
```

### Persistent Storage

BrainPalace stores data in three locations:

| Storage | Purpose | Size Estimate |
|---------|---------|---------------|
| ChromaDB | Vector embeddings | ~1GB per 100K chunks |
| BM25 Index | Keyword index | ~100MB per 100K chunks |
| Graph Index | Knowledge graph | ~200MB per 50K entities |

**Recommendation**: Use SSD storage for best performance.

### systemd Service

Create `/etc/systemd/system/brainpalace.service`:

```ini
[Unit]
Description=BrainPalace RAG Server
After=network.target

[Service]
Type=simple
User=brainpalace
Group=brainpalace
WorkingDirectory=/opt/brainpalace
Environment=OPENAI_API_KEY=sk-proj-...
Environment=CHROMA_PERSIST_DIR=/data/brainpalace/vectors
Environment=BM25_INDEX_PATH=/data/brainpalace/bm25
ExecStart=/opt/brainpalace/venv/bin/brainpalace-serve --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable brainpalace
sudo systemctl start brainpalace
sudo systemctl status brainpalace
```

---

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --no-cache-dir \
    brainpalace-rag \
    brainpalace-cli

# Create data directories
RUN mkdir -p /data/vectors /data/bm25 /data/graph

# Set environment defaults
ENV API_HOST=0.0.0.0
ENV API_PORT=8000
ENV CHROMA_PERSIST_DIR=/data/vectors
ENV BM25_INDEX_PATH=/data/bm25
ENV GRAPH_INDEX_PATH=/data/graph

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run server
CMD ["brainpalace-serve", "--host", "0.0.0.0", "--port", "8000"]
```

### docker-compose.yml

```yaml
version: '3.8'

services:
  brainpalace:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - ENABLE_GRAPH_INDEX=true
      - GRAPH_STORE_TYPE=simple
    volumes:
      - brainpalace-data:/data
      - ./docs:/docs:ro  # Mount documents to index
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  brainpalace-data:
```

### Running with Docker

```bash
# Build image
docker build -t brainpalace .

# Run container
docker run -d \
  --name brainpalace \
  -p 8000:8000 \
  -e OPENAI_API_KEY="sk-proj-..." \
  -v brainpalace-data:/data \
  -v /path/to/docs:/docs:ro \
  brainpalace

# Index documents
docker exec brainpalace brainpalace index /docs

# Check status
docker exec brainpalace brainpalace status
```

### Docker Compose Deployment

```bash
# Set environment
export OPENAI_API_KEY="sk-proj-..."
export ANTHROPIC_API_KEY="sk-ant-..."

# Start services
docker-compose up -d

# Index documents
docker-compose exec brainpalace brainpalace index /docs

# View logs
docker-compose logs -f brainpalace
```

---

## Resource Requirements

### Minimum Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 2 cores | 4 cores |
| RAM | 2GB | 8GB |
| Storage | 10GB | 50GB SSD |
| Python | 3.10+ | 3.11+ |

### Memory Sizing

Memory usage scales with:

1. **Number of chunks**: ~1KB per chunk in memory during indexing
2. **Vector dimensions**: 3072 dimensions = ~12KB per vector
3. **Graph size**: ~1MB per 1000 entities

**Guidelines**:

| Project Size | Documents | Chunks | RAM Needed |
|--------------|-----------|--------|------------|
| Small | < 1,000 | < 10,000 | 2GB |
| Medium | 1,000-10,000 | 10,000-100,000 | 4-8GB |
| Large | 10,000+ | 100,000+ | 8-16GB |

### CPU Considerations

- **Indexing**: CPU-intensive during embedding generation
- **Queries**: Mostly I/O-bound, scales with concurrent requests
- **GraphRAG**: LLM extraction is API-bound, not CPU-bound

---

## Monitoring and Observability

### Health Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Basic health check (for load balancers) |
| `GET /health/status` | Detailed status (indexing progress, counts) |

### Prometheus Metrics (Future)

BrainPalace will support Prometheus metrics in a future release. For now, use log-based monitoring.

### Logging

BrainPalace logs to stdout/stderr with configurable levels:

```bash
# Enable debug logging
DEBUG=true brainpalace-serve

# Log format
# 2024-01-15 10:30:00 [INFO] brainpalace_server.api.main: Starting BrainPalace RAG server...
```

### Log Aggregation

For production, use a log aggregator:

```yaml
# docker-compose with logging
services:
  brainpalace:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### Alerting Suggestions

Set up alerts for:

- Health endpoint returns non-healthy status
- Query latency exceeds threshold (e.g., > 5 seconds)
- Indexing fails repeatedly
- Disk usage exceeds 80%

---

## Security Considerations

### Network Security

By default, BrainPalace binds to `127.0.0.1`, accessible only from localhost.

**For network access**, use a reverse proxy:

```nginx
# nginx configuration
server {
    listen 443 ssl;
    server_name brainpalace.example.com;

    ssl_certificate /etc/ssl/certs/brainpalace.crt;
    ssl_certificate_key /etc/ssl/private/brainpalace.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Basic auth
        auth_basic "BrainPalace";
        auth_basic_user_file /etc/nginx/.htpasswd;
    }
}
```

### API Key Security

**Never commit API keys to version control.**

Options for secure storage:

1. **Environment variables**: Set in systemd or Docker
2. **Secrets manager**: AWS Secrets Manager, HashiCorp Vault
3. **.env files**: Keep out of version control with `.gitignore`

```bash
# .gitignore
.env
.env.local
.env.production
```

### Data Security

- Indexed content is stored locally in unencrypted format
- Consider disk encryption for sensitive codebases
- Limit file permissions on storage directories

```bash
# Secure storage directory
chmod 700 /data/brainpalace
chown brainpalace:brainpalace /data/brainpalace
```

### CORS Configuration

The default CORS configuration allows all origins:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production!
)
```

For production, restrict to specific origins.

---

## Troubleshooting

### Common Issues

#### Server Won't Start

**Symptoms**: `Address already in use` or server exits immediately.

**Solutions**:
```bash
# Check what's using the port
lsof -i :8000

# Kill existing process
kill -9 $(lsof -t -i :8000)

# Or use a different port
brainpalace start --port 8080
```

#### Out of Memory During Indexing

**Symptoms**: Process killed or OOM errors during indexing.

**Solutions**:
1. Index in smaller batches
2. Increase available memory
3. Reduce chunk overlap
4. Disable LLM summaries

```bash
# Index specific folders instead of entire project
brainpalace index ./docs
brainpalace index ./src/module1
brainpalace index ./src/module2
```

#### Slow Query Performance

**Symptoms**: Queries take > 5 seconds.

**Causes and Solutions**:

| Cause | Solution |
|-------|----------|
| Large result sets | Reduce `top_k` |
| Complex graph queries | Reduce `traversal_depth` |
| Cold start | First query after restart is slow |
| Slow disk | Use SSD storage |

#### ChromaDB Corruption

**Symptoms**: Errors about corrupted database or missing files.

**Solution**:
```bash
# Reset and re-index
brainpalace reset --yes
brainpalace index /path/to/documents
```

#### API Key Errors

**Symptoms**: `AuthenticationError` or `Invalid API key`.

**Solutions**:
```bash
# Verify key is set
echo $OPENAI_API_KEY

# Check key format (should start with sk-proj-)
# Regenerate key if needed at platform.openai.com
```

### Debug Mode

Enable debug mode for detailed logging:

```bash
DEBUG=true brainpalace start
```

This enables:
- Detailed request/response logging
- Stack traces for errors
- Auto-reload on code changes

### Getting Help

1. Check logs: `docker-compose logs brainpalace`
2. Verify health: `curl http://localhost:8000/health`
3. Check status: `brainpalace status`
4. GitHub Issues: Report bugs with logs and reproduction steps

---

## Backup and Recovery

### Backup Strategy

Back up these directories regularly:

```bash
# Backup locations
CHROMA_PERSIST_DIR=/data/brainpalace/vectors
BM25_INDEX_PATH=/data/brainpalace/bm25
GRAPH_INDEX_PATH=/data/brainpalace/graph
```

**Backup script**:

```bash
#!/bin/bash
DATE=$(date +%Y%m%d)
BACKUP_DIR=/backups/brainpalace

mkdir -p $BACKUP_DIR

# Stop server for consistent backup
brainpalace stop

# Create backup
tar -czf $BACKUP_DIR/brainpalace-$DATE.tar.gz \
    /data/brainpalace/vectors \
    /data/brainpalace/bm25 \
    /data/brainpalace/graph

# Restart server
brainpalace start --daemon

# Cleanup old backups (keep 7 days)
find $BACKUP_DIR -name "*.tar.gz" -mtime +7 -delete
```

### Recovery

```bash
# Stop server
brainpalace stop

# Restore from backup
tar -xzf /backups/brainpalace/brainpalace-20240115.tar.gz -C /

# Restart server
brainpalace start --daemon
```

### Re-indexing

If indexes are corrupted beyond recovery:

```bash
# Reset all indexes
brainpalace reset --yes

# Re-index from source documents
brainpalace index /path/to/documents
```

---

## Next Steps

- [API Reference](API_REFERENCE.md) - Complete API documentation
- [Configuration Reference](CONFIGURATION.md) - All configuration options
- [Architecture Overview](ARCHITECTURE.md) - System design
