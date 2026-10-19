"""Risk score from the exported HGNN embeddings.

    score = h_user · h_object
    p     = σ(score)        how likely this user is to be connected to this object
    risk  = 1 − p

This is the HGNN's own dot-product decoder, so no extra model is needed (docs/ai-design.md, section 4).
Only numpy is used: the service does not need torch.
"""  # noqa: E501

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class RiskResult:
    risk: float | None  # None when the user or object has no embedding
    high_risk: bool
    reason: str | None = None


class RiskModel:
    def __init__(
        self,
        users: dict[str, np.ndarray],
        objects: dict[str, np.ndarray],
        threshold: float,
        metadata: dict,
    ):
        self.users = users
        self.objects = objects
        self.threshold = threshold
        self.metadata = metadata

    @classmethod
    def load(cls, model_dir: str | Path, threshold: float | None = None) -> "RiskModel":
        """Load the hgnn-job output. `threshold` overrides the calibrated one in metadata.json."""
        model_dir = Path(model_dir)
        metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
        node_ids = json.loads((model_dir / "node_ids.json").read_text(encoding="utf-8"))
        user_type, _, object_type = metadata["target_edge_type"]

        if threshold is None:
            if "risk_threshold" not in metadata:
                raise ValueError(
                    f"{model_dir / 'metadata.json'} has no risk_threshold; "
                    "re-export with hgnn-job or set AI_RISK_THRESHOLD"
                )
            threshold = metadata["risk_threshold"]["value"]

        with np.load(model_dir / "embeddings.npz") as embeddings:
            users = dict(zip(node_ids[user_type], embeddings[user_type], strict=True))
            objects = dict(zip(node_ids[object_type], embeddings[object_type], strict=True))
        return cls(users, objects, threshold, metadata)

    def risk(self, user: str, obj: str) -> RiskResult:
        h_user, h_object = self.users.get(user), self.objects.get(obj)
        if h_user is None:
            return RiskResult(risk=None, high_risk=False, reason="unknown user")
        if h_object is None:
            return RiskResult(risk=None, high_risk=False, reason="unknown object")

        risk = 1 - _sigmoid(float(np.dot(h_user, h_object)))
        return RiskResult(risk=risk, high_risk=risk > self.threshold)


def _sigmoid(x: float) -> float:
    # Written in two branches so exp() never overflows for large |x|.
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)
