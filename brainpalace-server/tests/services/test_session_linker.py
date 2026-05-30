"""Cross-session linking: canonicalisation, supersession, promotion (Phase 140)."""

from __future__ import annotations

from brainpalace_server.models.session_extract import SessionExtraction
from brainpalace_server.services.session_linker import (
    apply_supersessions,
    canonicalize_entity,
    promote_decisions,
)


# --------------------------------------------------------------- canonicalise
class TestCanonicalize:
    def test_relative_and_absolute_paths_collapse(self, tmp_path) -> None:
        root = str(tmp_path)
        (tmp_path / "auth.py").write_text("x")
        a = canonicalize_entity("auth.py", root)
        b = canonicalize_entity("./auth.py", root)
        c = canonicalize_entity(str(tmp_path / "auth.py"), root)
        assert a == b == c == "auth.py"

    def test_nested_path_posix(self, tmp_path) -> None:
        root = str(tmp_path)
        assert canonicalize_entity("src/pkg/mod.py", root) == "src/pkg/mod.py"

    def test_non_path_entity_unchanged(self, tmp_path) -> None:
        assert canonicalize_entity("Redis cache backend", str(tmp_path)) == (
            "Redis cache backend"
        )

    def test_path_outside_root_unchanged(self, tmp_path) -> None:
        # an absolute path not under the project root is left as-is
        out = canonicalize_entity("/etc/hosts", str(tmp_path))
        assert out == "/etc/hosts"

    def test_empty_root_is_noop(self) -> None:
        assert canonicalize_entity("auth.py", "") == "auth.py"


# ---------------------------------------------------------------- supersession
class FakeGraph:
    """Minimal graph honouring the manager surface 140 uses."""

    def __init__(self) -> None:
        self.decisions: dict[str, str] = {}  # name -> node
        self.edges: list[dict] = []  # {subject,predicate,object,valid}
        self.invalidated: list[tuple[str, str, str]] = []

    def find_decision_nodes(self, text: str) -> list[str]:
        norm = text.strip().lower()
        return [n for n in self.decisions if n.strip().lower() == norm]

    def timeline(self, entity: str) -> list[dict]:
        return [
            e for e in self.edges if entity in (e["subject"], e["object"])
        ]

    def invalidate(self, subject, predicate, obj, at=None) -> int:
        self.invalidated.append((subject, predicate, obj))
        hit = 0
        for e in self.edges:
            if (
                e["subject"] == subject
                and e["predicate"] == predicate
                and e["object"] == obj
                and e["valid"]
            ):
                e["valid"] = False
                hit += 1
        return hit


def _payload(**kw) -> SessionExtraction:
    base = {"session_id": "s1", "summary": "s", "decisions": [], "triplets": []}
    base.update(kw)
    return SessionExtraction(**base)


class TestSupersession:
    def test_supersession_invalidates_old_facts_preserves_history(self) -> None:
        g = FakeGraph()
        g.decisions["use in-memory cache"] = "node"
        # the old decision had a stale fact + the new superseded-by history edge
        g.edges = [
            {
                "subject": "use in-memory cache",
                "predicate": "touches",
                "object": "cache.py",
                "valid": True,
            },
            {
                "subject": "use in-memory cache",
                "predicate": "superseded-by",
                "object": "use Redis cache",
                "valid": True,
            },
        ]
        payload = _payload(
            decisions=[
                {"text": "use Redis cache", "supersedes": "use in-memory cache"}
            ]
        )
        n = apply_supersessions(payload, g, project_root="")
        assert n == 1
        # the stale fact is closed...
        assert ("use in-memory cache", "touches", "cache.py") in g.invalidated
        # ...but the superseded-by history edge is preserved (never invalidated)
        assert all(p != "superseded-by" for (_s, p, _o) in g.invalidated)

    def test_superseded_by_triplet_drives_supersession(self) -> None:
        g = FakeGraph()
        g.decisions["old plan"] = "node"
        g.edges = [
            {
                "subject": "old plan",
                "predicate": "decided",
                "object": "x",
                "valid": True,
            }
        ]
        payload = _payload(
            triplets=[
                {"subject": "old plan", "relation": "superseded-by", "object": "new"}
            ]
        )
        assert apply_supersessions(payload, g, project_root="") == 1
        assert ("old plan", "decided", "x") in g.invalidated

    def test_unresolvable_prior_is_skipped(self) -> None:
        g = FakeGraph()  # no matching decision node
        payload = _payload(decisions=[{"text": "new", "supersedes": "never recorded"}])
        assert apply_supersessions(payload, g, project_root="") == 0
        assert g.invalidated == []

    def test_no_temporal_support_is_noop(self) -> None:
        class Plain:  # lacks find_decision_nodes/timeline/invalidate
            pass

        payload = _payload(decisions=[{"text": "b", "supersedes": "a"}])
        assert apply_supersessions(payload, Plain(), project_root="") == 0


# ------------------------------------------------------------------ promotion
class FakeMemory:
    def __init__(self) -> None:
        self.added: list[str] = []

    async def add(  # noqa: ANN001,ANN201
        self, text, section="Project", tags=None, origin="user", confidence=1.0
    ):
        self.added.append(text)

    def load(self):
        return []


class TestPromotion:
    async def test_current_decision_with_rationale_promoted(self) -> None:
        mem = FakeMemory()
        payload = _payload(
            decisions=[
                {"text": "adopt Redis", "rationale": "speed", "supersedes": None},
            ]
        )
        n = await promote_decisions(payload, mem)
        assert n == 1
        assert any("adopt Redis" in t for t in mem.added)

    async def test_decision_without_rationale_skipped(self) -> None:
        mem = FakeMemory()
        payload = _payload(decisions=[{"text": "do thing", "rationale": None}])
        assert await promote_decisions(payload, mem) == 0

    async def test_none_memory_service_is_noop(self) -> None:
        payload = _payload(
            decisions=[{"text": "x", "rationale": "y"}]
        )
        assert await promote_decisions(payload, None) == 0
