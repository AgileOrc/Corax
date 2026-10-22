import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class RiskResult:
    risk: float | None
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
        model_dir = Path(model_dir)
        metadata = json.loads((model_dir / "metadata.json").read_text(encoding="utf-8"))
        node_ids = json.loads((model_dir / "node_ids.json").read_text(encoding="utf-8"))
        user_type, _, object_type = metadata["target_edge_type"]

        if threshold is None:
            if "risk_threshold" not in metadata:
                raise ValueError(
                    f"{model_dir / 'metadata.json'} has no risk_threshold; "
                    "retrain with python -m hgnn or set AI_RISK_THRESHOLD"
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
    if x >= 0:
        return 1 / (1 + math.exp(-x))
    e = math.exp(x)
    return e / (1 + e)
