"""Reciprocal-rank fusion for cross-instance query merge (spec R2-2 M1).

Scores from different BrainPalace instances are not comparable (different
embedding models, corpus-dependent BM25), so fusion is rank-based:
RRF(d) = sum over lists of 1/(k + rank_d)."""

from __future__ import annotations

from typing import Any


def rrf_merge(
    result_lists: list[tuple[str, list[dict[str, Any]]]],
    k: int = 60,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}
    for label, results in result_lists:
        for rank, r in enumerate(results, start=1):
            # Compute the fallback id once per result so a missing chunk_id
            # dedups consistently between the scoring pass and the payload
            # stored in ``fused`` (both must agree on the same key).
            cid = r.get("chunk_id") or f"{label}:{rank}"
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            if cid not in fused:
                fused[cid] = {**r, "instance": label}

    ordered = sorted(
        fused.items(),
        key=lambda item: scores[item[0]],
        reverse=True,
    )
    return [payload for _cid, payload in ordered[:top_k]]
