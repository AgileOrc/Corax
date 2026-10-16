import json
import subprocess
import sys
from pathlib import Path

import pytest
from corax_hgnn.export import load, save
from corax_hgnn.graph import load_graph
from corax_hgnn.train import TrainConfig, train

TOY = Path(__file__).parent / "fixtures" / "toy_graph"
RUN = Path(__file__).parents[2] / "hgnn-job" / "run.py"
FAST = TrainConfig(hidden=16, learning_rate=0.01, max_epochs=50, patience=5, seed=0)


@pytest.fixture
def exported(tmp_path):
    graph = load_graph(TOY, "accessed")
    result = train(graph, FAST)
    save(result, graph, FAST, tmp_path)
    return graph, result, tmp_path


def test_writes_all_output_files(exported):
    _, _, out = exported

    for name in ["embeddings.npz", "node_ids.json", "metadata.json", "history.csv"]:
        assert (out / name).exists()


def test_load_returns_one_row_per_node_in_id_order(exported):
    graph, _, out = exported

    embeddings, node_ids = load(out)

    assert node_ids == graph.node_ids
    for node_type, ids in node_ids.items():
        assert embeddings[node_type].shape == (len(ids), 16)


def test_metadata_records_training_results(exported):
    _, result, out = exported

    metadata = json.loads((out / "metadata.json").read_text(encoding="utf-8"))

    assert metadata["target_edge_type"] == ["lecturer", "accessed", "student"]
    assert metadata["best_epoch"] == result.best_epoch
    assert metadata["val_auc"] == result.val_auc
    assert metadata["config"]["hidden"] == 16
    assert metadata["num_nodes"]["student"] == 6


def test_history_has_one_row_per_epoch(exported):
    _, result, out = exported

    rows = (out / "history.csv").read_text(encoding="utf-8").strip().splitlines()

    assert rows[0] == "epoch,train_loss,val_loss"
    assert len(rows) - 1 == len(result.history)


def test_command_line_runs_end_to_end(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(RUN),
            "--data", str(TOY),
            "--target-relation", "accessed",
            "--out", str(tmp_path),
            "--hidden", "8",
            "--max-epochs", "5",
        ],
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip

    assert completed.returncode == 0, completed.stderr
    assert "val AUC" in completed.stdout
    assert (tmp_path / "embeddings.npz").exists()
