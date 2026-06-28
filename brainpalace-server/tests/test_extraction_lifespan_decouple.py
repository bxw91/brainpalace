"""Plan 4 C1 (keystone) — the provider doc drain must be decoupled from sessions.

The reconciler that owns the doc adapter was constructed only inside the
session-capability gate (``caps.archive_enabled or caps.index_enabled or
distill_would_run``) — all session signals. With sessions fully off and
``extraction.mode=provider``, the reconciler never started and the provider doc
backlog grew forever (silently-incomplete graph, the §1 defect this effort kills).

Booting the full lifespan in a unit test is impractical (storage backend,
embedder, providers). Mirroring ``test_doc_pending_store_lifespan_order.py``, we
pin the C1 invariants structurally against the lifespan source: the modes/flags
are resolved once and stashed on ``app.state``, a ``doc_extraction_would_run``
term exists, and it is OR'd into BOTH the outer setup gate and the inner
reconciler-construction gate so docs run with sessions off.
"""

from __future__ import annotations

import inspect

import brainpalace_server.api.main as main


def _src() -> str:
    return inspect.getsource(main.lifespan)


def test_modes_and_flags_resolved_and_stashed_at_lifespan() -> None:
    src = _src()
    for attr in (
        "app.state.extraction_mode_doc = resolve_extraction_mode(",
        "app.state.extraction_mode_session = resolve_extraction_mode(",
        "app.state.extraction_provider_enabled = extraction_provider_enabled(",
        "app.state.graphrag_enabled =",
        "app.state.extraction_grace_hours =",
        "app.state.extraction_drain_batch =",
        "app.state.extraction_drain_cooldown =",
        "app.state.summarization_label =",
        "app.state.summarization_available =",
    ):
        assert attr in src, f"lifespan must stash {attr!r} on app.state (C1/C2/M4)"


def test_doc_extraction_would_run_term_exists_with_two_locks() -> None:
    src = _src()
    assert "doc_extraction_would_run = (" in src, "C1 doc gate term missing"
    start = src.index("doc_extraction_would_run = (")
    block = src[start : start + 400]
    # graphrag enable + mode in provider/auto + H2 provider lock + store present.
    assert "app.state.graphrag_enabled" in block
    assert 'app.state.extraction_mode_doc in ("provider", "auto")' in block
    assert "app.state.extraction_provider_enabled" in block, "H2 second lock missing"
    assert "app.state.doc_pending_store is not None" in block


def test_doc_term_decouples_outer_and_inner_gates() -> None:
    src = _src()
    # Outer setup gate: docs run even with archive/index/distill all off.
    outer = src.index("or distill_would_run")
    assert (
        "doc_extraction_would_run" in src[outer : outer + 120]
    ), "doc_extraction_would_run must be OR'd into the outer session-setup gate"
    # Inner reconciler-construction gate (was archive_service/sess_svc/distiller).
    inner = src.index("reconciler = SessionReconciler(")
    pre = src[:inner]
    gate_idx = pre.rindex("distiller is not None")
    assert (
        "doc_extraction_would_run" in pre[gate_idx : gate_idx + 120]
    ), "doc_extraction_would_run must gate the SessionReconciler construction"


def test_config_knobs_wired_into_adapter_and_reconciler() -> None:
    src = _src()
    # M4: throttle from config, not literals.
    assert "drain_max_count=app.state.extraction_drain_batch" in src
    assert "drain_cooldown=app.state.extraction_drain_cooldown" in src
    # C3 + H1: doc adapter receives the resolved graphrag flag, mode, lock, grace.
    assert "graphrag_enabled=app.state.graphrag_enabled" in src
    assert "mode=app.state.extraction_mode_doc" in src
    assert "provider_enabled=app.state.extraction_provider_enabled" in src
    assert "grace_hours=app.state.extraction_grace_hours" in src
