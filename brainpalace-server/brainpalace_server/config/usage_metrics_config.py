"""`usage_metrics:` config section. Self-contained (read directly by the
lifespan + the recorder gate), not mapped onto flat Settings env vars."""

from __future__ import annotations

from pydantic import BaseModel, Field

from brainpalace_server.config.provider_config import load_raw_config


class UsageMetricsConfig(BaseModel):
    enabled: bool = Field(
        default=True,
        description="Record usage/spend telemetry to .brainpalace/usage_metrics.db",
    )
    # NB: no ge= bound — retain_days <= 0 means keep forever (§6-F1).
    retain_days: int = Field(
        default=7,
        description=(
            "Keep telemetry for the N most-recent *active* days (days with no "
            "activity don't count); <= 0 = keep forever"
        ),
    )


def load_usage_metrics_config() -> UsageMetricsConfig:
    raw = load_raw_config() or {}
    section = raw.get("usage_metrics") or {}
    return UsageMetricsConfig.model_validate(section)
