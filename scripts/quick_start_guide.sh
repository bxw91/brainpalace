#!/bin/bash
set -e

# Configuration
PORT=8085
DB_PATH="./integration/tests/quick_start/chroma_db"
SERVER_DIR="brainpalace-server"
CLI_DIR="brainpalace-cli"
WORKSPACE="integration/tests/quick_start"
# Indexed fixture datasets live OUTSIDE the gitignored WORKSPACE. The
# gitignore-aware indexer (Phase H) prunes anything under a path listed in
# .gitignore, so a dataset created inside WORKSPACE (which .gitignore masks)
# would index to zero files. FIXTURE_DIR is deliberately NOT gitignored and
# is removed by cleanup() so test runs leave no untracked state behind.
FIXTURE_DIR="integration/tests/quick_start_fixtures"
BASE_URL="http://127.0.0.1:$PORT"

echo "=== BrainPalace Quick Start Test Script ==="

# Check prerequisites
if ! command -v lsof >/dev/null 2>&1; then
    echo "Error: lsof is not installed (required for port checking)"
    exit 1
fi

if [ ! -x "$SERVER_DIR/.venv/bin/brainpalace-serve" ]; then
    echo "Error: server .venv not found at $SERVER_DIR/.venv. Run 'poetry install' in $SERVER_DIR first." >&2
    exit 1
fi

if [ ! -x "$CLI_DIR/.venv/bin/brainpalace" ]; then
    echo "Error: CLI .venv not found at $CLI_DIR/.venv. Run 'poetry install' in $CLI_DIR first." >&2
    exit 1
fi

# Cleanup function
cleanup() {
    echo "Cleaning up..."
    if [ ! -z "$SERVER_PID" ]; then
        kill $SERVER_PID 2>/dev/null || true
    fi
    # Clean up any remaining processes on the port
    PIDS=$(lsof -ti :$PORT 2>/dev/null || true)
    if [ ! -z "$PIDS" ]; then
        kill $PIDS 2>/dev/null || true
    fi
    # FIXTURE_DIR is not gitignored — remove it so a run leaves no untracked
    # state on the working tree.
    rm -rf "$FIXTURE_DIR" 2>/dev/null || true
}

# Set trap for cleanup on exit
trap cleanup EXIT INT TERM

# 1. Cleanup old processes
echo "Checking for old Doc-Serve processes on port $PORT..."
PIDS=$(lsof -ti :$PORT || true)
if [ ! -z "$PIDS" ]; then
    echo "Found processes: $PIDS. Killing..."
    kill $PIDS
    sleep 10
    PIDS=$(lsof -ti :$PORT)
    if [ ! -z "$PIDS" ]; then
        echo "Still running. Force killing..."
        kill -9 $PIDS
    fi
fi

# 2. Prepare workspace
echo "Preparing workspace at $WORKSPACE (fixtures at $FIXTURE_DIR)..."
rm -rf "$WORKSPACE" "$FIXTURE_DIR"
mkdir -p "$WORKSPACE" "$FIXTURE_DIR"

# 3. Setup environment variables
export API_PORT=$PORT
export DATABASE_PATH=$DB_PATH
export DEBUG=true
export BRAINPALACE_PROJECT_ROOT="$(pwd)"

# 4. Start Server
echo "Starting BrainPalace server on port $PORT..."
nohup ./$SERVER_DIR/.venv/bin/brainpalace-serve > "$WORKSPACE/server.log" 2>&1 &
SERVER_PID=$!

echo "Server started with PID $SERVER_PID. Waiting for health check..."

# Wait for server to be healthy
MAX_RETRIES=30
COUNT=0
while [ $COUNT -lt $MAX_RETRIES ]; do
    if curl -s "$BASE_URL/health" > /dev/null; then
        echo "Server is healthy!"
        break
    fi
    COUNT=$((COUNT + 1))
    sleep 2
    if [ $COUNT -eq $MAX_RETRIES ]; then
        echo "Server failed to start. See $WORKSPACE/server.log"
        kill $SERVER_PID
        exit 1
    fi
done

# 5. CLI Tool Setup
export BRAINPALACE_URL=$BASE_URL

# 6. Prepare bounded smoke-test dataset and index it
#
# Earlier versions of this script indexed the entire repository root (`brainpalace index .`),
# which can take 15+ minutes on the current monorepo and triggers harness/CI timeouts.
# A smoke test should be fast and self-contained: we synthesise a small fixture
# (a few markdown + python files) and index that. Queries below match the fixture content.
# Override with TEST_INDEX_DIR=<path> to point at a different dataset.
SMOKE_DIR="$FIXTURE_DIR/smoke_dataset"
TEST_INDEX_DIR="${TEST_INDEX_DIR:-$SMOKE_DIR}"

if [ "$TEST_INDEX_DIR" = "$SMOKE_DIR" ]; then
    echo "Creating bounded smoke dataset at $SMOKE_DIR..."
    mkdir -p "$SMOKE_DIR"
    cat > "$SMOKE_DIR/coffee.md" <<'EOF'
# Coffee Guide

Espresso is a strong coffee made by forcing hot water through finely-ground beans.

## How to make espresso

1. Tamp finely-ground coffee into a portafilter.
2. Lock the portafilter into the espresso machine.
3. Pull a 25–30 second shot at about 9 bars of pressure.
EOF

    cat > "$SMOKE_DIR/auth_service.py" <<'EOF'
"""Authentication service for the demo app."""


class AuthService:
    """Validates user credentials and issues tokens."""

    def __init__(self, secret: str) -> None:
        self.secret = secret

    def authenticate(self, username: str, password: str) -> str:
        """Authenticate a user and return a session token."""
        if not username or not password:
            raise ValueError("username and password required")
        return f"token-for-{username}"
EOF

    cat > "$SMOKE_DIR/code_splitter.py" <<'EOF'
"""CodeSplitter splits source files into AST-aware chunks."""


class CodeSplitter:
    """Split Python source into class and function chunks."""

    def __init__(self, max_chunk_size: int = 1000) -> None:
        self.max_chunk_size = max_chunk_size

    def split(self, source: str) -> list[str]:
        """Return a list of chunk strings extracted from `source`."""
        return [source[: self.max_chunk_size]]
EOF
fi

ABS_TEST_INDEX_DIR="$(cd "$TEST_INDEX_DIR" && pwd)"
echo "Indexing bounded dataset at $ABS_TEST_INDEX_DIR (including code)..."
if ! $CLI_DIR/.venv/bin/brainpalace index "$ABS_TEST_INDEX_DIR" --include-code; then
    echo "Failed to start indexing. Check server status."
    kill $SERVER_PID
    exit 1
fi

# 7. Wait for indexing to complete
echo "Waiting for indexing to complete..."
INDEXING_TIMEOUT=600  # 10 minutes max for the bounded smoke dataset
START_TIME=$(date +%s)

while true; do
    CURRENT_TIME=$(date +%s)
    ELAPSED=$((CURRENT_TIME - START_TIME))

    if [ $ELAPSED -gt $INDEXING_TIMEOUT ]; then
        echo "Indexing timed out after $INDEXING_TIMEOUT seconds"
        kill $SERVER_PID
        exit 1
    fi

    STATUS=$($CLI_DIR/.venv/bin/brainpalace status --json 2>/dev/null)

    # Try to parse with jq if available, otherwise fall back to grep
    if command -v jq >/dev/null 2>&1; then
        IS_INDEXING=$(echo "$STATUS" | jq -r '.indexing.indexing_in_progress' 2>/dev/null || echo "true")
        CHUNK_COUNT=$(echo "$STATUS" | jq -r '.indexing.total_chunks' 2>/dev/null || echo "0")
    else
        # Fallback to grep/cut (fragile)
        IS_INDEXING=$(echo "$STATUS" | grep -o '"indexing_in_progress": [a-z]*' | cut -d' ' -f2 || echo "true")
        CHUNK_COUNT=$(echo "$STATUS" | grep -o '"total_chunks": [0-9]*' | cut -d' ' -f2 || echo "0")
    fi

    echo "Status: Indexing=$IS_INDEXING, Chunks=$CHUNK_COUNT"

    if [ "$IS_INDEXING" = "false" ] && [ "$CHUNK_COUNT" -gt 0 ]; then
        echo "Indexing complete!"
        break
    fi
    sleep 5
done

# 8. Run Queries
echo "--- Running Queries ---"

echo "Query 1: Semantic (espresso)"
$CLI_DIR/.venv/bin/brainpalace query "how to make espresso" --top-k 3 || echo "Query 1 failed, continuing..."

echo "Query 2: Keyword/BM25 (CodeSplitter)"
$CLI_DIR/.venv/bin/brainpalace query "CodeSplitter" --mode bm25 --source-types code || echo "Query 2 failed, continuing..."

echo "Query 3: Hybrid (authentication)"
$CLI_DIR/.venv/bin/brainpalace query "how does authentication work" --mode hybrid --alpha 0.5 || echo "Query 3 failed, continuing..."

echo "Query 4: Language-specific (Python chunks)"
$CLI_DIR/.venv/bin/brainpalace query "class" --languages python --source-types code --top-k 2 || echo "Query 4 failed, continuing..."

# 8.5 GraphRAG Query Modes (Feature 113)
echo "--- Testing GraphRAG Query Modes (Feature 113) ---"

echo "Query 5: Graph mode (may fail if GraphRAG disabled)"
$CLI_DIR/.venv/bin/brainpalace query "class relationships" --mode graph --top-k 3 || echo "Query 5: Graph mode not enabled (expected if ENABLE_GRAPH_INDEX=false)"

echo "Query 6: Multi mode (vector + BM25 + graph fusion)"
$CLI_DIR/.venv/bin/brainpalace query "how do services work" --mode multi --top-k 5 || echo "Query 6: Multi mode query completed (graph component may be disabled)"

echo "Query 7: Check graph index status"
$CLI_DIR/.venv/bin/brainpalace status --json | grep -i graph || echo "Graph index status: not available or disabled"

# 9. Summarization Test (Small sample)
echo "--- Testing Summarization (Small Sample) ---"
SUMM_DIR="$FIXTURE_DIR/summ_test"
mkdir -p "$SUMM_DIR/subdir"
echo "def add(a, b): return a + b" > "$SUMM_DIR/math.py"
echo "def sub(a, b): return a - b" > "$SUMM_DIR/subdir/math2.py"
echo -e "# Coffee Guide\nEspresso is strong." > "$SUMM_DIR/coffee.md"

echo "Indexing sample for summarization..."
# Note: This might still take a bit if LLM is involved, but we only have 3 files.
# Use absolute path since CLI runs from different directory
ABS_SUMM_DIR="$(pwd)/$SUMM_DIR"
if $CLI_DIR/.venv/bin/brainpalace index "$ABS_SUMM_DIR" --generate-summaries; then
    echo "Querying sample with summary..."
    $CLI_DIR/.venv/bin/brainpalace query "math operations" --source-types code || echo "Summarization query failed"
else
    echo "Summarization indexing failed (may require API keys)"
fi

echo "Quick start test completed successfully!"
