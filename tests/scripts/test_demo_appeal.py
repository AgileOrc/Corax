import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]


@pytest.fixture
def opa():
    for found in (os.environ.get("OPA_PATH"), shutil.which("opa"), ROOT.parent / "opa.exe"):
        if found and Path(found).exists():
            return str(found)
    pytest.skip("opa not found (set OPA_PATH)")


def run(*args):
    completed = subprocess.run(
        [sys.executable, *map(str, args)], capture_output=True, text=True, encoding="utf-8", check=False, cwd=ROOT
    )
    return completed


@pytest.fixture(scope="module")
def dummy_model(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dummy")
    data, model = tmp / "data", tmp / "model"
    for args in (
        (ROOT / "scripts/prepare/make_dummy.py", data),
        ("-m", "hgnn", "--data", data, "--target-relation", "accessed", "--out", model, "--learning-rate", "0.01", "--patience", "50"),
    ):
        completed = run(*args)
        assert completed.returncode == 0, completed.stderr
    return model


def test_three_appeals_and_the_opa_checks(dummy_model, opa, tmp_path):
    saved = {f.name: f.stat().st_mtime_ns for f in dummy_model.iterdir()}

    completed = run(ROOT / "scripts/demo_appeal.py", "--model-dir", dummy_model, "--opa", opa, "--out", tmp_path / "out")

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "-> rule_applied" in completed.stdout
    assert "-> 409" in completed.stdout
    assert "-> exception_only" in completed.stdout
    assert "8/8 expectations met" in completed.stdout
    written = sorted(p.name for p in (tmp_path / "out" / "generated").glob("*.rego"))
    assert written == ["appeal-0001-exception.rego", "appeal-0001-rule.rego", "appeal-0002-exception.rego", "appeal-0003-exception.rego"]
    assert {f.name: f.stat().st_mtime_ns for f in dummy_model.iterdir()} == saved


def test_refuses_a_folder_that_is_not_empty(dummy_model, opa, tmp_path):
    (tmp_path / "keep.txt").write_text("mine", encoding="utf-8")

    completed = run(ROOT / "scripts/demo_appeal.py", "--model-dir", dummy_model, "--opa", opa, "--out", tmp_path)

    assert completed.returncode != 0
    assert "is not empty" in completed.stderr
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "mine"
