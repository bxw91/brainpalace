"""Shared rendering for the dry-run embedding-token estimate.

Used by both ``brainpalace index --estimate`` and the opt-in pre-index prompt
in ``brainpalace init`` so the two surfaces print an identical advisory.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console


def _human_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def print_token_estimate(console: Console, est: dict[str, Any]) -> None:
    """Render the server's estimate dict as a short advisory block."""
    files = est.get("files", 0)
    tokens = est.get("est_embedding_tokens", 0)
    console.print(
        f"\n[bold]Estimated embedding usage[/] "
        f"[dim](approximate — {est.get('tokenizer', 'heuristic')})[/]"
    )
    console.print(
        f"  Files: [bold]{files:,}[/] "
        f"([cyan]{est.get('code_files', 0):,}[/] code · "
        f"[cyan]{est.get('doc_files', 0):,}[/] docs · "
        f"{_human_bytes(est.get('total_bytes', 0))})"
    )
    console.print(
        f"  Embedding tokens: [bold yellow]~{tokens:,}[/] "
        f"[dim](overlap ×{est.get('overlap_factor', 1.0)} · "
        f"{est.get('embedding_provider', '?')}/{est.get('embedding_model', '?')})[/]"
    )
    git_tokens = est.get("git_tokens", 0)
    session_tokens = est.get("session_tokens", 0)
    if git_tokens or session_tokens:
        _segments = [f"[dim]docs[/] ~{est.get('doc_tokens', 0):,}"]
        if git_tokens:
            _segments.append(
                f"[dim]git[/] ~{git_tokens:,} ({est.get('git_commits', 0):,} commits)"
            )
        if session_tokens:
            _segments.append(f"[dim]sessions[/] ~{session_tokens:,}")
        console.print("    " + " · ".join(_segments))
    if est.get("summaries_enabled"):
        console.print(
            "  [yellow]Note:[/] code summaries are ON — that adds a separate "
            "LLM (summarisation) bill on top of these embedding tokens."
        )
    console.print(
        "  [dim]Approximate: provider tokenizers, overlap and summaries vary "
        "the real figure (±~30%). First index is full; re-index is cheaper "
        "(embedding cache).[/]\n"
    )
