"""Regression: DocPendingStore must be constructed BEFORE the session
reconciler block consumes it (Unified Extraction, Plan 2).

The session-reconciler block is gated by ``archive_service or sess_svc or
distiller`` — archive is ON by default, so on a default install that block runs
and builds ``DocExtractionAdapter(store=app.state.doc_pending_store, ...)``. If
``app.state.doc_pending_store`` is assigned LATER in the lifespan, the attribute
does not exist yet → ``AttributeError`` → swallowed by the session block's
``except`` → the session reconciler never starts (a silent default-path
regression that mypy and scoped tests miss because it is execution-order).

This pins the ordering invariant directly in the lifespan source. It fails
against the buggy order (assignment after the reconciler block) and passes once
the DocPendingStore construction is moved before it.
"""

from __future__ import annotations

import inspect

import brainpalace_server.api.main as main


def test_doc_pending_store_assigned_before_reconciler_consumes_it() -> None:
    src = inspect.getsource(main.lifespan)

    assign = src.index("app.state.doc_pending_store = DocPendingStore")
    adapter_ref = src.index("store=app.state.doc_pending_store")
    reconciler = src.index("reconciler = SessionReconciler(")

    # The store must be assigned before the doc adapter references it AND before
    # the SessionReconciler that receives the adapters is constructed.
    assert assign < adapter_ref, (
        "DocPendingStore is assigned AFTER the doc adapter references "
        "app.state.doc_pending_store — the session reconciler block runs first "
        "(archive ON by default) and will AttributeError."
    )
    assert (
        assign < reconciler
    ), "DocPendingStore must be constructed before the SessionReconciler block."
