"""Parse a project server's /openapi.json into a flat capability list."""

from __future__ import annotations

from typing import Any


def parse_openapi(doc: dict[str, Any]) -> list[dict[str, str]]:
    """Flatten an OpenAPI doc into ``{method, path, summary, tag}`` rows."""
    caps: list[dict[str, str]] = []
    for path, methods in (doc.get("paths") or {}).items():
        for method, spec in methods.items():
            tags = spec.get("tags") or [""]
            caps.append(
                {
                    "method": method.upper(),
                    "path": path,
                    "summary": spec.get("summary", ""),
                    "tag": tags[0],
                }
            )
    return caps
