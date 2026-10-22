import json
import subprocess
import sys
from pathlib import Path

import pytest
import torch

from hgnn.export import load, load_trained, save, save_graph
from hgnn.graph import load_graph
from hgnn.train import TrainConfig, train

TOY = Path(__file__).parent / "fixtures" / "toy_graph"
ROOT = Path(__file__).parents[2]
FAST = TrainConfig(hidden=16, learning_rate=0.01, max_epochs=50, patience=5, seed=0)


@pytest.fixture
def exported(tmp_path):
    graph = load_graph(TOY, "accessed")
    result = train(graph, FAST)
    save(result, graph, FAST, tmp_path)
    return graph, result, tmp_path


def test_writes_all_output_files(exported):
    _, _, out = exported

    for name in ["embeddings.npz", "node_ids.json", "metadata.json", "history.csv", "model.pt", "split.pt"]:
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


def test_metadata_records_calibrated_risk_threshold(exported):
    _, _, out = exported

    threshold = json.loads((out / "metadata.json").read_text(encoding="utf-8"))["risk_threshold"]

    assert threshold["target_pass_rate"] == 0.99
    assert 0.0 <= threshold["value"] <= 1.0
    assert threshold["val_false_deny_rate"] <= 0.01


def test_history_has_one_row_per_epoch(exported):
    _, result, out = exported

    rows = (out / "history.csv").read_text(encoding="utf-8").strip().splitlines()

    assert rows[0] == "epoch,train_loss,val_loss"
    assert len(rows) - 1 == len(result.history)


def test_trained_model_can_be_loaded_again(tmp_path):
    graph = load_graph(TOY, "accessed")
    result = train(graph, FAST)
    save(result, graph, FAST, tmp_path, data_folder=TOY)

    model, loaded_graph, split, metadata = load_trained(tmp_path)

    assert metadata["data"] == str(TOY)
    assert loaded_graph.node_ids == graph.node_ids
    for name, weights in result.model.state_dict().items():
        assert torch.equal(model.state_dict()[name], weights)
    assert torch.equal(split["test_data"][graph.target].edge_label_index,
                       result.test_data[graph.target].edge_label_index)
    assert torch.equal(split["val_probs"], result.val_probs)


def test_loading_needs_the_data_folder(exported):
    _, _, out = exported

    with pytest.raises(ValueError, match="no data folder"):
        load_trained(out)
    model, _, _, _ = load_trained(out, data_folder=TOY)
    assert model is not None


def test_graph_json_has_structure_but_no_access_history(tmp_path):
    path = save_graph(TOY, "accessed", tmp_path)

    graph = json.loads(path.read_text(encoding="utf-8"))

    assert graph["lecturer_budi"] == {
        "advises": ["student_ani"],
        "holds": ["position_head_of_program"],
        "member_of": ["program_IF"],
        "teaches": ["course_IF201"],
    }
    assert graph["student_candra"] == {
        "enrolled_in": ["course_IF201", "course_IF202"],
        "member_of": ["program_IF"],
    }
    assert all("accessed" not in relations for relations in graph.values())


def test_access_json_holds_only_the_target_relation(tmp_path):
    save_graph(TOY, "accessed", tmp_path)

    access = json.loads((tmp_path / "access.json").read_text(encoding="utf-8"))

    assert access["lecturer_budi"] == ["student_ani", "student_candra"]
    assert access["lecturer_tono"] == ["student_dewi", "student_eko", "student_gita"]
    assert sum(len(objects) for objects in access.values()) == 10


def test_graph_json_is_stable(tmp_path):
    first = save_graph(TOY, "accessed", tmp_path / "a").read_text(encoding="utf-8")
    second = save_graph(TOY, "accessed", tmp_path / "b").read_text(encoding="utf-8")

    assert first == second
    assert list(json.loads(first)) == sorted(json.loads(first))


def test_command_line_runs_end_to_end(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "hgnn",
            "--data", str(TOY),
            "--target-relation", "accessed",
            "--out", str(tmp_path),
            "--hidden", "8",
            "--max-epochs", "5",
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    assert "val AUC" in completed.stdout
    assert "risk threshold" in completed.stdout
    assert (tmp_path / "embeddings.npz").exists()
    assert (tmp_path / "graph.json").exists()
