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
    console.print(
        "  [dim]Approximate: provider tokenizers and overlap vary "
        "the real figure (±~30%). First index is full; re-index is cheaper "
        "(embedding cache).[/]\n"
    )


def print_folder_estimate(
    console: Console,
    est: dict[str, Any],
    *,
    stale: bool,
    bp_excludes: list[str],
    session_gitignore: list[str],
) -> None:
    """Render the per-folder token breakdown + the two ignore lists.

    Folders are alphabetical with ``(root files)`` pinned last. Columns are
    overlap-inflated token counts; the header names the tokenizer. Tokens only —
    no cost figure. ``stale`` flags that an edit changed the exclude set since the
    numbers below were computed (re-estimate to refresh)."""
    from rich.table import Table

    tok = est.get("tokenizer", "heuristic")
    banner = " [yellow](stale — run re-estimate to refresh)[/]" if stale else ""
    console.print(
        f"\n[bold]Token estimate[/] [dim](tokenizer: {tok} · overlap-inflated)[/]"
        f"{banner}"
    )

    rows = list(est.get("by_folder", []))
    rows.sort(key=lambda r: (r["name"] == "(root files)", r["name"].lower()))

    table = Table(show_edge=False, pad_edge=False, box=None)
    table.add_column("Folder")
    table.add_column("Files", justify="right")
    table.add_column("Code tok", justify="right")
    table.add_column("Doc tok", justify="right")
    tot_f = tot_c = tot_d = 0
    for r in rows:
        table.add_row(
            r["name"],
            f"{r['files']:,}",
            f"{r['code_tokens']:,}",
            f"{r['doc_tokens']:,}",
        )
        tot_f += r["files"]
        tot_c += r["code_tokens"]
        tot_d += r["doc_tokens"]
    table.add_row(
        "[bold]TOTAL[/]",
        f"[bold]{tot_f:,}[/]",
        f"[bold]{tot_c:,}[/]",
        f"[bold]{tot_d:,}[/]",
    )
    console.print(table)
    console.print(f"  [dim]≈ {tot_c + tot_d:,} tokens (approximate, ±~30%)[/]")

    console.print("\n[dim]Ignored — BrainPalace config (cleared on reset):[/]")
    console.print("  " + (", ".join(bp_excludes) if bp_excludes else "[dim](none)[/]"))
    if session_gitignore:
        console.print("[dim]Added to .gitignore this session (saved, permanent):[/]")
        console.print("  " + ", ".join(session_gitignore))
