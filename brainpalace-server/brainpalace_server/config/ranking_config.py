"""Per-project retrieval-ranking config (config.yaml `ranking:` section).

doc_weight soft-multiplies a doc chunk's score in the query tail. Default 0.5
(docs half-weight vs code). 1.0 = docs equal to code; 0.0 = docs hard-dropped
from results (still indexed). A first-class config value: rendered in the CLI
config grid and the dashboard like any other field.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RankingConfig(BaseModel):
    doc_weight: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "How much documentation is trusted vs code when searching: "
            "1.0 = docs ranked equal to code, 0.5 = docs half-weight (default), "
            "0.0 = docs excluded from results (still indexed)."
        ),
    )

    reference_rank_penalty: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description=(
            "Rank multiplier for results from reference-authority sources "
            "(external folders): 1.0 = no penalty, 0.7 = default soft penalty, "
            "0.0 = reference results excluded (still indexed)."
        ),
    )

    def weight_for(self, source_type: str) -> float:
        return self.doc_weight if source_type == "doc" else 1.0
