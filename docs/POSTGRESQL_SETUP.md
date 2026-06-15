---
last_validated: 2026-06-15
---

# PostgreSQL + pgvector Setup (Docker Compose)

This guide explains how to run a local PostgreSQL instance with pgvector for the BrainPalace PostgreSQL backend.

## Requirements

- Docker Desktop with Docker Compose v2
- The provided pgvector Compose template
- BrainPalace configured with `storage.backend: "postgres"`

## Template Location

The repository includes a ready-to-run template:

```
brainpalace-plugin/templates/docker-compose.postgres.yml
```

Copy it into your project root (recommended so `docker compose` finds it):

```bash
cp brainpalace-plugin/templates/docker-compose.postgres.yml ./docker-compose.postgres.yml
```

## Environment Variables

The template supports these optional overrides:

- `POSTGRES_PASSWORD` (default: `brainpalace_dev`)
- `POSTGRES_PORT` (default: `5432`)

Example:

```bash
export POSTGRES_PASSWORD="supersecret"
export POSTGRES_PORT="5432"
```

## Start PostgreSQL

```bash
docker compose -f docker-compose.postgres.yml up -d
```

## Readiness Checks

Confirm the container is healthy:

```bash
docker compose -f docker-compose.postgres.yml ps
```

Check readiness inside the container:

```bash
docker compose -f docker-compose.postgres.yml exec postgres \
  pg_isready -U brainpalace -d brainpalace
```

## pgvector Requirement

BrainPalace requires the pgvector extension. The template uses the
`pgvector/pgvector:pg16` image so the extension is available.

If you use a different PostgreSQL image, ensure `pgvector` is installed,
or schema creation will fail with `extension "vector" does not exist`.

## Configure BrainPalace

After PostgreSQL is running, configure the storage backend and connection
settings in `config.yaml` (typically at `.brainpalace/config.yaml`):

```yaml
storage:
  backend: "postgres"
  postgres:
    host: "localhost"
    port: 5432
    database: "brainpalace"
    user: "brainpalace"
    password: "brainpalace_dev"
    pool_size: 10
    pool_max_overflow: 10
    pool_timeout: 30
    language: "english"
    hnsw_m: 16
    hnsw_ef_construction: 64
    debug: false
```

**Pool settings:**

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `pool_size` | int | `10` | Number of connections to keep in the pool |
| `pool_max_overflow` | int | `10` | Extra connections allowed above `pool_size` |
| `pool_timeout` | int | `30` | Seconds to wait for a connection from the pool before raising a timeout error |

These field names correspond to the `storage.backend` and `storage.postgres.*`
keys in the server's configuration schema. See `docs/CONFIGURATION.md` for the
full schema reference.

### DATABASE_URL Override

As an alternative to individual `storage.postgres.*` keys, you can set the
`DATABASE_URL` environment variable to override the connection string. Pool
settings and HNSW tuning parameters still come from YAML:

```bash
export DATABASE_URL="postgresql+asyncpg://brainpalace:brainpalace_dev@localhost:5432/brainpalace"
```

You can also set the storage backend via environment variable:

```bash
export BRAINPALACE_STORAGE_BACKEND="postgres"
```

## Important: No Auto-Migration

BrainPalace does not auto-migrate data between backends. If you switch
from ChromaDB to PostgreSQL (or vice versa), you must re-index your
documents after the change.

## Next Steps

- Update `storage.backend` and `storage.postgres` in `config.yaml`
- Restart the BrainPalace server
- Run `brainpalace reset --yes` and re-index your documents
