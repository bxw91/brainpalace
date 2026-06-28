"""Session source adapter — thin delegation to the existing distiller (Plan 2).

The reconciler lift must not change session distill OUTPUT (spec §6 guardrail),
so this adapter adds no extraction logic: select = archive-gap (pending_sessions),
process = SessionDistiller.maybe_distill. Throttling/pacing is the only change,
owned by the reconciler tick.
"""

from __future__ import annotations

from typing import Any

from brainpalace_server.services.session_distill_service import pending_sessions


class SessionExtractionAdapter:
    name = "session"

    def __init__(
        self, *, distiller: Any | None, project_root: str, archive_dir: str
    ) -> None:
        self._distiller = distiller
        self._project_root = project_root
        self._archive_dir = archive_dir

    @property
    def is_ready(self) -> bool:
        return self._distiller is not None

    async def select_pending(self, limit: int) -> list[str]:
        # 2-7: select with the SAME quiescence threshold the distiller uses, so a
        # not-yet-quiescent session isn't surfaced only for maybe_distill to defer
        # it (which drain_once would miscount as a failure and a spent slot).
        kwargs: dict[str, Any] = {}
        idle = getattr(self._distiller, "idle_seconds", None)
        if idle is not None:
            kwargs["idle_seconds"] = idle
        pairs = pending_sessions(self._project_root, self._archive_dir, **kwargs)
        return [path for _sid, path in pairs[:limit]]

    async def process(self, item: str) -> bool:
        if self._distiller is None:
            return False
        result = await self._distiller.maybe_distill(item)
        return result is not None
