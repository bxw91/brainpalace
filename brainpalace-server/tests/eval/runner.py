"""Eval runner: build a throwaway index over the fixture corpus and run cases.

Drives the *real* server through an in-process FastAPI ``TestClient`` so the
whole indexing + query pipeline (chunking, embeddings, BM25, fusion) is the same
code a user hits — no re-implementation, no mocks. The index lives in a fresh
temp ``BRAINPALACE_STATE_DIR`` and is torn down after the run.

Usage:
    python -m tests.eval.runner               # run all cases, print raw hits
    python -m tests.eval.runner --one <id>    # run a single case (debugging)
"""

from __future__ import annotations

import argparse
import contextlib
import os
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_DIR = EVAL_DIR / "corpus"
CASES_PATH = EVAL_DIR / "cases.yaml"
# Graph-mode cases (Phase 160). Loaded + scored only with graph=True, because
# they require ENABLE_GRAPH_INDEX=true at index time; the default keyless-ish
# run must not include them (graph mode errors when the graph is disabled).
CASES_GRAPH_PATH = EVAL_DIR / "cases_graph.yaml"

# Pinned eval embedding model — cheap + deterministic per model. A baseline is
# only comparable under the same model; this is documented in docs/EVALUATION.md.
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"

# How long to wait for the indexing job to finish before giving up.
INDEX_TIMEOUT_SECONDS = 180


@dataclass
class CaseResult:
    """Retrieved sources for one case (scoring happens in scorer.py)."""

    id: str
    query: str
    mode: str
    k: int
    expected: list[str]
    retrieved: list[str] = field(default_factory=list)
    error: str | None = None


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    with open(path) as f:
        cases = yaml.safe_load(f) or []
    if not isinstance(cases, list):
        raise ValueError(f"{path} must contain a YAML list of cases")
    return cases


@contextlib.contextmanager
def _indexed_client(
    corpus_dir: Path, embedding_model: str, graph: bool = False
) -> Iterator[Any]:
    """Yield a TestClient backed by a fresh temp index over ``corpus_dir``.

    When ``graph`` is True, ENABLE_GRAPH_INDEX is turned on so the index job
    builds the knowledge graph and GRAPH-mode cases can be scored (Phase 160).
    """
    tmp = tempfile.mkdtemp(prefix="brainpalace-eval-")
    state_dir = Path(tmp) / ".brainpalace"
    state_dir.mkdir(parents=True, exist_ok=True)

    # Must be set BEFORE importing the app so Settings() and the lifespan pick
    # them up. Keep the eval quiet; graph is off unless explicitly requested.
    os.environ["BRAINPALACE_STATE_DIR"] = str(state_dir)
    os.environ["EMBEDDING_MODEL"] = embedding_model
    os.environ["ENABLE_GRAPH_INDEX"] = "true" if graph else "false"

    # Pin BOTH providers to OpenAI in a state-dir config.yaml. provider_config
    # reads <state_dir>/config.yaml (search priority 2). Without this the
    # summarization provider defaults to Anthropic and EmbeddingGenerator
    # construction dies on a missing ANTHROPIC_API_KEY during lifespan — eval
    # never generates summaries, but the provider is still constructed. OpenAI
    # is the only live provider in CI/dev (OPENAI_API_KEY); api_key_env must be
    # overridden for summarization (its default is ANTHROPIC_API_KEY).
    (state_dir / "config.yaml").write_text(
        "embedding:\n"
        "  provider: openai\n"
        f"  model: {embedding_model}\n"
        "  api_key_env: OPENAI_API_KEY\n"
        "summarization:\n"
        "  provider: openai\n"
        "  model: gpt-4o-mini\n"
        "  api_key_env: OPENAI_API_KEY\n"
    )

    # Guard: never index against a non-temp state dir by accident.
    assert tmp.startswith(tempfile.gettempdir()), "eval must use a temp state dir"

    from fastapi.testclient import TestClient

    from brainpalace_server.api.main import app

    with TestClient(app) as client:
        # Enqueue an indexing job for the corpus (outside the temp project →
        # allow_external).
        resp = client.post(
            "/index",
            params={"allow_external": True},
            # include_code defaults False — the corpus has .py files whose
            # content several cases expect, so code indexing must be on.
            json={"folder_path": str(corpus_dir), "include_code": True},
        )
        resp.raise_for_status()
        job_id = resp.json()["job_id"]

        deadline = time.time() + INDEX_TIMEOUT_SECONDS
        while time.time() < deadline:
            job = client.get(f"/index/jobs/{job_id}").json()
            status = job.get("status")
            # The job API reports terminal success as "done" (not "completed").
            if status in ("done", "completed", "failed", "cancelled"):
                if status not in ("done", "completed"):
                    raise RuntimeError(f"indexing job ended: {job}")
                break
            time.sleep(1)
        else:
            raise TimeoutError(
                f"indexing did not finish within {INDEX_TIMEOUT_SECONDS}s"
            )

        yield client


def _query(client: Any, query: str, mode: str, k: int) -> list[str]:
    resp = client.post(
        "/query",
        json={"query": query, "mode": mode, "top_k": k},
    )
    resp.raise_for_status()
    return [r["source"] for r in resp.json().get("results", [])]


def run_eval(
    cases: list[dict[str, Any]] | None = None,
    corpus_dir: Path = CORPUS_DIR,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    only: str | None = None,
    graph: bool = False,
) -> list[CaseResult]:
    """Build the index once, run every case, return per-case retrieved sources.

    With ``graph=True`` the graph index is built and the graph-mode cases
    (``cases_graph.yaml``) are appended (Phase 160).
    """
    if cases is None:
        cases = load_cases()
        if graph and CASES_GRAPH_PATH.exists():
            cases = cases + load_cases(CASES_GRAPH_PATH)
    if only:
        cases = [c for c in cases if c["id"] == only]
        if not cases:
            raise SystemExit(f"no case with id={only!r}")

    results: list[CaseResult] = []
    with _indexed_client(corpus_dir, embedding_model, graph=graph) as client:
        for c in cases:
            cr = CaseResult(
                id=c["id"],
                query=c["query"],
                mode=c["mode"],
                k=int(c["k"]),
                expected=list(c["expected"]),
            )
            try:
                cr.retrieved = _query(client, c["query"], c["mode"], cr.k)
            except Exception as exc:  # noqa: BLE001 — record, don't abort the run
                cr.error = f"{type(exc).__name__}: {exc}"
            results.append(cr)
    return results


def _main() -> None:
    ap = argparse.ArgumentParser(description="Run retrieval eval cases.")
    ap.add_argument("--one", help="run a single case by id")
    ap.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    ap.add_argument(
        "--graph",
        action="store_true",
        help="enable the graph index + run graph-mode cases (Phase 160)",
    )
    args = ap.parse_args()

    for cr in run_eval(only=args.one, embedding_model=args.model, graph=args.graph):
        status = "ERR" if cr.error else "ok"
        print(f"[{status}] {cr.id} ({cr.mode}) expected={cr.expected}")
        if cr.error:
            print(f"      error: {cr.error}")
        else:
            for src in cr.retrieved:
                print(f"      → {src}")


if __name__ == "__main__":
    _main()
