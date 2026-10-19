import json

import numpy as np
import pytest

THRESHOLD = 0.5


@pytest.fixture
def threshold():
    return THRESHOLD


@pytest.fixture
def model_dir(tmp_path):
    """A tiny hand-made hgnn-job output, so the scores are easy to check.

    u1 · r1 = 2·2 = 4   -> p = σ(4)  ≈ 0.982 -> risk ≈ 0.018 (normal)
    u1 · r2 = 2·-2 = -4 -> p = σ(-4) ≈ 0.018 -> risk ≈ 0.982 (high)
    """
    np.savez(
        tmp_path / "embeddings.npz",
        user=np.array([[2.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        resource=np.array([[2.0, 0.0], [-2.0, 0.0]], dtype=np.float32),
        department=np.array([[1.0, 1.0]], dtype=np.float32),
    )
    node_ids = {"user": ["u1", "u2"], "resource": ["r1", "r2"], "department": ["d1"]}
    (tmp_path / "node_ids.json").write_text(json.dumps(node_ids), encoding="utf-8")
    metadata = {
        "created_at": "2026-10-19T00:00:00+00:00",
        "target_edge_type": ["user", "has_access", "resource"],
        "risk_threshold": {"value": THRESHOLD, "target_pass_rate": 0.99},
    }
    (tmp_path / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return tmp_path
