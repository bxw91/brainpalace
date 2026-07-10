"""Server-side provider curation (rides `extraction.mode=provider`/`auto`).

Mirrors SessionDistiller: uses the configured summarization provider to curate the
curated-memory file (dedupe/obsolete/consolidate). Gated by the caller (lifespan) on
mode ∈ {provider,auto} + extraction_provider_enabled(); this module, once invoked,
only reads the weekly stamp and either succeeds-and-stamps or fails-and-leaves-unstamped
(retried next sweep). All mutations go through MemoryService (cap + lock honored)."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Protocol

from brainpalace_server.config.settings import settings
from brainpalace_server.storage_paths import STATE_SUBDIR, state_file_path

logger = logging.getLogger(__name__)

_STAMP = "last-curate"
#: Cap on entries described to the model per run (bounds prompt + blast radius).
_DEFAULT_MAX_ENTRIES = 50


class _Summarizer(Protocol):
    async def generate(self, prompt: str) -> str: ...


_PROMPT = """\
You are curating a list of durable memory facts. Return ONLY minified JSON with keys:
  "delete":  [ids of near-duplicate or redundant entries to remove],
  "obsolete":[{{"id": id, "superseded_by": id_or_null}} for logically stale entries].
Do not invent ids. Prefer keeping the clearest, most recent phrasing. Entries:
{entries}
JSON:"""


class MemoryCurator:
    def __init__(
        self,
        summarizer: _Summarizer,
        memory_service: Any,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._summ = summarizer
        self._mem = memory_service
        self._max_entries = max_entries

    def _due(self, state_dir: Path) -> bool:
        stamp = state_dir / STATE_SUBDIR / _STAMP
        interval = getattr(settings, "MEMORY_CURATE_INTERVAL_DAYS", 7) * 86400
        try:
            if stamp.exists() and time.time() - stamp.stat().st_mtime < interval:
                return False
        except Exception:  # noqa: BLE001 — unreadable stamp → treat as due
            return True
        return True

    def _stamp(self, state_dir: Path) -> None:
        try:
            state_file_path(state_dir, _STAMP).touch()
        except OSError as exc:
            logger.debug("curate stamp failed: %s", exc)

    async def curate_if_due(self, state_dir: Path) -> int:
        if not self._due(state_dir):
            return 0
        active = [m for m in self._mem.load() if m.is_active]
        if not active:
            return 0
        entries = "\n".join(
            f"- id={m.id}: {m.text}" for m in active[: self._max_entries]
        )
        try:
            reply = await self._summ.generate(_PROMPT.format(entries=entries))
            ops = self._parse(reply, {m.id for m in active})
        except Exception as exc:  # noqa: BLE001 — provider/parse failure → retry later
            logger.warning("memory curation run failed (will retry): %s", exc)
            return 0
        changed = 0
        for mid in ops["delete"]:
            try:
                await self._mem.delete(mid)
                changed += 1
            except Exception as exc:  # noqa: BLE001 — one bad id must not abort the run
                logger.debug("curate delete %s failed: %s", mid, exc)
        for ob in ops["obsolete"]:
            try:
                await self._mem.obsolete(
                    ob["id"], superseded_by=ob.get("superseded_by")
                )
                changed += 1
            except Exception as exc:  # noqa: BLE001
                logger.debug("curate obsolete %s failed: %s", ob, exc)
        # A completed run stamps even at 0 changes (respects cadence); only a
        # provider/parse FAILURE above leaves the stamp untouched for retry.
        self._stamp(state_dir)
        logger.info("memory curation: %d entries changed", changed)
        return changed

    @staticmethod
    def _parse(reply: str, valid_ids: set[str]) -> dict[str, list[Any]]:
        """Defensive JSON parse restricted to known ids. Raises on malformed input."""
        data = json.loads(reply.strip())
        if not isinstance(data, dict):
            raise ValueError("curation reply is not a JSON object")
        delete = [i for i in data.get("delete", []) if i in valid_ids]
        obsolete = [
            {"id": o["id"], "superseded_by": o.get("superseded_by")}
            for o in data.get("obsolete", [])
            if isinstance(o, dict) and o.get("id") in valid_ids
        ]
        return {"delete": delete, "obsolete": obsolete}
