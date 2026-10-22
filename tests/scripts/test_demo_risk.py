import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
TOY = ROOT / "tests" / "hgnn" / "fixtures" / "toy_graph"


def run(*args):
    return subprocess.run(
        [sys.executable, *map(str, args)], capture_output=True, text=True, encoding="utf-8", check=False, cwd=ROOT
    )


def train(out, test_ratio):
    trained = run("-m", "hgnn", "--data", TOY, "--target-relation", "accessed", "--out", out,
                  "--test-ratio", test_ratio, "--hidden", "8", "--max-epochs", "5")
    assert trained.returncode == 0, trained.stderr


def test_demo_scores_held_out_pairs_without_training(tmp_path):
    train(tmp_path, "0.2")
    saved = {f.name: f.stat().st_mtime_ns for f in tmp_path.iterdir()}

    completed = run(ROOT / "scripts" / "demo_risk.py", "--model-dir", tmp_path, "--show", "2")

    assert completed.returncode == 0, completed.stderr
    assert "none seen during training" in completed.stdout
    assert "allowed" in completed.stdout and "let through" in completed.stdout
    assert {f.name: f.stat().st_mtime_ns for f in tmp_path.iterdir()} == saved


def test_demo_refuses_a_model_without_test_split(tmp_path):
    train(tmp_path, "0")

    completed = run(ROOT / "scripts" / "demo_risk.py", "--model-dir", tmp_path)

    assert completed.returncode != 0
    assert "--test-ratio 0" in completed.stderr
