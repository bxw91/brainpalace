"""Plan B Task 1 — exact-name node lookup for the entity resolver."""

from __future__ import annotations

from pathlib import Path

import pytest

from brainpalace_server.config import settings
from brainpalace_server.storage.graph_store import GraphStoreManager
from brainpalace_server.storage.sqlite_graph_store import SQLitePropertyGraphStore


class _N:
    def __init__(
        self, id: str, name: str, label: str = "File", domain: str = "code"
    ) -> None:
        self.id, self.name, self.label, self.domain = id, name, label, domain
        self.properties: dict = {}


@pytest.fixture(autouse=True)
def _enable_graph(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ENABLE_GRAPH_INDEX", True)
    GraphStoreManager.reset_instance()
    yield
    GraphStoreManager.reset_instance()


@pytest.fixture()
def store() -> SQLitePropertyGraphStore:
    s = SQLitePropertyGraphStore(":memory:")
    s.upsert_nodes(
        [
            _N("/repo/src/auth.py", "auth.py"),
            _N("/repo/src/auth.py:login", "login", label="Function"),
            _N("/repo/tests/auth.py", "auth.py"),
            _N("git-author:a@b.c", "Ada", label="Author", domain="git"),
            _N("session-node-login", "login", label="Decision", domain="session"),
        ]
    )
    return s


def test_exact_match_and_shape(store: SQLitePropertyGraphStore) -> None:
    rows = store.nodes_by_exact_name("login", domains=["code"])
    assert rows == [
        {
            "id": "/repo/src/auth.py:login",
            "name": "login",
            "label": "Function",
            "domain": "code",
        }
    ]


def test_case_sensitive(store: SQLitePropertyGraphStore) -> None:
    assert store.nodes_by_exact_name("Login", domains=["code"]) == []


def test_no_substring_match(store: SQLitePropertyGraphStore) -> None:
    assert store.nodes_by_exact_name("log", domains=["code"]) == []


def test_domain_filter(store: SQLitePropertyGraphStore) -> None:
    all_rows = store.nodes_by_exact_name("login")
    assert {r["domain"] for r in all_rows} == {"code", "session"}


def test_ambiguous_returns_all(store: SQLitePropertyGraphStore) -> None:
    rows = store.nodes_by_exact_name("auth.py", domains=["code"])
    assert len(rows) == 2


def test_limit(store: SQLitePropertyGraphStore) -> None:
    rows = store.nodes_by_exact_name("auth.py", domains=["code"], limit=1)
    assert len(rows) == 1


class TestManagerWrapper:
    def test_sqlite_backend(self, tmp_path: Path) -> None:
        mgr = GraphStoreManager(
            persist_dir=tmp_path / "graph_index", store_type="sqlite"
        )
        mgr.initialize()
        mgr.add_triplet(
            "auth.py",
            "contains",
            "login",
            subject_id="/repo/src/auth.py",
            object_id="/repo/src/auth.py:login",
            subject_name="auth.py",
            object_name="login",
            object_type="Function",
        )
        rows = mgr.nodes_by_exact_name("login", domains=["code"])
        assert [r["id"] for r in rows] == ["/repo/src/auth.py:login"]

    def test_simple_backend_empty(self, tmp_path: Path) -> None:
        mgr = GraphStoreManager(
            persist_dir=tmp_path / "graph_index", store_type="simple"
        )
        mgr.initialize()
        assert mgr.nodes_by_exact_name("anything") == []
