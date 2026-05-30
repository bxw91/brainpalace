"""Eval report: run the harness, print scores, and diff against a baseline.

    python -m tests.eval.report                  # run + print table (+ json blob)
    python -m tests.eval.report --baseline       # also diff vs baseline.json
    python -m tests.eval.report --update-baseline # overwrite baseline.json
    python -m tests.eval.report --json           # machine-readable only

The eval is **directional, not pass/fail** — this command exits 0 even when a
metric drops; the drop is printed visibly (and, with ``--strict``, sets a
non-zero exit) so a regression shows up in review instead of silently.

A baseline is only comparable under the same pinned embedding model
(see ``runner.DEFAULT_EMBEDDING_MODEL`` / docs/EVALUATION.md). Refreshing the
baseline is explicit (``--update-baseline``) and should carry a written reason
in the commit message — never rubber-stamp it to mask a regression.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tests.eval.runner import DEFAULT_EMBEDDING_MODEL, run_eval
from tests.eval.scorer import CaseScore, score_all

EVAL_DIR = Path(__file__).resolve().parent
BASELINE_PATH = EVAL_DIR / "baseline.json"

# A metric must drop by more than this to count as a regression (scores wobble).
EPSILON = 0.02


def build_report(
    scores: list[CaseScore], summary: dict[str, Any], model: str
) -> dict[str, Any]:
    return {
        "model": model,
        "summary": summary,
        "cases": [
            {
                "id": s.id,
                "mode": s.mode,
                "k": s.k,
                "recall_at_k": round(s.recall, 4),
                "rr": round(s.rr, 4),
                "hit": s.hit,
                "error": s.error,
            }
            for s in scores
        ],
    }


def _fmt(v: float) -> str:
    return f"{v:.3f}"


def print_table(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(f"\nEval model: {report['model']}")
    print("=" * 60)
    print(f"{'mode':<10}{'cases':>7}{'errors':>8}{'recall@k':>11}{'mrr':>8}")
    print("-" * 60)
    for mode in sorted(summary["by_mode"]):
        m = summary["by_mode"][mode]
        print(
            f"{mode:<10}{m['cases']:>7}{m['errors']:>8}"
            f"{_fmt(m['recall_at_k']):>11}{_fmt(m['mrr']):>8}"
        )
    o = summary["overall"]
    print("-" * 60)
    print(
        f"{'OVERALL':<10}{o['cases']:>7}{o['errors']:>8}"
        f"{_fmt(o['recall_at_k']):>11}{_fmt(o['mrr']):>8}"
    )
    delta = summary["mode_agreement"]["hybrid_vs_bm25_mrr_delta"]
    if delta is not None:
        sign = "+" if delta >= 0 else ""
        print(f"\nmode-agreement: hybrid MRR vs bm25 = {sign}{_fmt(delta)}")

    misses = [c for c in report["cases"] if not c["hit"]]
    if misses:
        print(f"\nmisses ({len(misses)}):")
        for c in misses:
            tag = "ERR" if c["error"] else "miss"
            print(f"  [{tag}] {c['id']} ({c['mode']})")


def diff_baseline(report: dict[str, Any], baseline_path: Path) -> list[str]:
    """Return human-readable regression lines (metrics that dropped > EPSILON)."""
    if not baseline_path.exists():
        return [f"no baseline at {baseline_path} — run with --update-baseline first"]

    base = json.loads(baseline_path.read_text())
    regressions: list[str] = []

    if base.get("model") != report.get("model"):
        regressions.append(
            f"model mismatch: baseline={base.get('model')} now={report.get('model')} "
            "— scores are not comparable"
        )

    cur_sum, base_sum = report["summary"], base["summary"]
    for metric in ("recall_at_k", "mrr"):
        cur = cur_sum["overall"][metric]
        old = base_sum["overall"][metric]
        if cur < old - EPSILON:
            regressions.append(
                f"overall {metric}: {old:.3f} -> {cur:.3f} (-{old - cur:.3f})"
            )
    for mode in cur_sum["by_mode"]:
        if mode not in base_sum["by_mode"]:
            continue
        for metric in ("recall_at_k", "mrr"):
            cur = cur_sum["by_mode"][mode][metric]
            old = base_sum["by_mode"][mode][metric]
            if cur < old - EPSILON:
                regressions.append(
                    f"{mode} {metric}: {old:.3f} -> {cur:.3f} (-{old - cur:.3f})"
                )

    # Per-case hit -> miss flips (sharpest signal of a real break).
    base_hits = {c["id"]: c["hit"] for c in base["cases"]}
    for c in report["cases"]:
        if base_hits.get(c["id"]) and not c["hit"]:
            regressions.append(f"case {c['id']} regressed: hit -> miss")

    return regressions


def _main() -> int:
    ap = argparse.ArgumentParser(description="Run + report retrieval eval scores.")
    ap.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    ap.add_argument(
        "--baseline", action="store_true", help="diff against baseline.json"
    )
    ap.add_argument(
        "--update-baseline",
        action="store_true",
        help="overwrite baseline.json with this run (explicit; needs a reason)",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="exit non-zero if --baseline finds a regression",
    )
    args = ap.parse_args()

    results = run_eval(embedding_model=args.model)
    scores, summary = score_all(results)
    report = build_report(scores, summary, args.model)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_table(report)

    if args.update_baseline:
        BASELINE_PATH.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nbaseline updated -> {BASELINE_PATH}")
        return 0

    if args.baseline:
        regressions = diff_baseline(report, BASELINE_PATH)
        if regressions:
            print("\n⚠ baseline regressions:")
            for r in regressions:
                print(f"  - {r}")
            if args.strict:
                return 1
        else:
            print("\n✓ no baseline regressions")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
