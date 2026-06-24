"""Seam #1 — open domain registry. Engine ships code/chat-life; a downstream
product registers its own at runtime. NEVER a closed Literal."""

from __future__ import annotations

DEFAULT_DOMAIN: str = "code"
_DOMAINS: set[str] = {"code", "chat-life"}


def register_domain(name: str) -> None:
    if not name or not name.strip():
        raise ValueError("domain name must be non-empty")
    _DOMAINS.add(name.strip())


def known_domains() -> frozenset[str]:
    return frozenset(_DOMAINS)


def is_known_domain(name: str) -> bool:
    return name in _DOMAINS
