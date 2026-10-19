# Settings read from environment variables.
# CORAX_MODEL_DIR     folder written by hgnn-job (embeddings.npz, node_ids.json, metadata.json)
# AI_RISK_THRESHOLD   optional; overrides the calibrated threshold from metadata.json

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    model_dir: Path
    risk_threshold: float | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        threshold = os.environ.get("AI_RISK_THRESHOLD")
        return cls(
            model_dir=Path(os.environ.get("CORAX_MODEL_DIR", "output/hgnn")),
            risk_threshold=float(threshold) if threshold else None,
        )
