import json
import os
import shutil
from pathlib import Path

import numpy as np
import pytest

THRESHOLD = 0.5
ROOT = Path(__file__).parents[2]


@pytest.fixture
def opa():
    for found in (os.environ.get("OPA_PATH"), shutil.which("opa"), ROOT.parent / "opa.exe"):
        if found and Path(found).exists():
            return str(found)
    pytest.skip("opa not found (set OPA_PATH)")


@pytest.fixture
def threshold():
    return THRESHOLD


@pytest.fixture
def model_dir(tmp_path):
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
