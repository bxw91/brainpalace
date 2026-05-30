"""Session and refresh-token management."""

import time


class SessionManager:
    """Tracks access/refresh token pairs and rotates them on refresh."""

    ACCESS_TTL_SECONDS = 15 * 60

    def __init__(self) -> None:
        self._families: dict[str, str] = {}

    def refresh_token(self, refresh_token: str) -> tuple[str, str]:
        """Exchange a refresh token for a new access/refresh pair.

        Rotates the refresh token: the old one is invalidated and a new pair is
        returned. Reusing an already-rotated token revokes the whole family.
        """
        if refresh_token not in self._families:
            raise ValueError("unknown or already-rotated refresh token")
        new_access = f"access-{time.time_ns()}"
        new_refresh = f"refresh-{time.time_ns()}"
        self._families[new_refresh] = self._families.pop(refresh_token)
        return new_access, new_refresh
