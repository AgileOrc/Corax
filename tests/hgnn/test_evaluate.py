import subprocess
import sys
from pathlib import Path

import pytest
import torch
from corax_hgnn.evaluate import (
    PASS_RATES,
    calibrate,
    calibrate_threshold,
    classification_metrics,
    confusion,
    evaluate,
    sample_hard_negatives,
    threshold_table,
)
from corax_hgnn.export import load_trained, save
from corax_hgnn.graph import load_graph
from corax_hgnn.train import TrainConfig, train

TOY = Path(__file__).parent / "fixtures" / "toy_graph"
SCRIPT = Path(__file__).parents[2] / "scripts" / "evaluate" / "evaluate_hgnn.py"
RUN = Path(__file__).parents[2] / "hgnn-job" / "run.py"
FAST = TrainConfig(hidden=16, learning_rate=0.01, max_epochs=50, patience=5, test_ratio=0.2)

LABELS = torch.tensor([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
PROBS = torch.tensor([0.9, 0.8, 0.4, 0.6, 0.2, 0.1])


@pytest.fixture
def graph():
    return load_graph(TOY, "accessed")


def test_confusion_matrix():
    assert confusion(LABELS, PROBS, 0.5) == {"tp": 2, "fp": 1, "tn": 2, "fn": 1}


def test_precision_recall_f1_accuracy():
    m = classification_metrics(LABELS, PROBS, 0.5)

    assert m["precision"] == pytest.approx(2 / 3)
    assert m["recall"] == pytest.approx(2 / 3)
    assert m["f1"] == pytest.approx(2 / 3)
    assert m["accuracy"] == pytest.approx(4 / 6)


def test_threshold_table_false_deny_and_detection():
    row = threshold_table(LABELS, PROBS, risk_thresholds=(0.5,))[0]

    assert row["false_deny_rate"] == pytest.approx(1 / 3)
    assert row["detection_rate"] == pytest.approx(2 / 3)


def test_calibrated_threshold_lets_the_target_share_of_real_access_pass():
    assert calibrate_threshold(LABELS, PROBS, 0.5) == pytest.approx(0.2)
    assert calibrate_threshold(LABELS, PROBS, 1.0) == pytest.approx(0.6)


@pytest.mark.parametrize("target", PASS_RATES)
def test_calibrated_pass_rate_is_never_below_target(target):
    generator = torch.Generator().manual_seed(0)
    labels = torch.ones(1000)
    probs = torch.rand(1000, generator=generator)

    threshold = calibrate_threshold(labels, probs, target)

    assert ((1 - probs) <= threshold).float().mean().item() >= target


def test_calibrate_reports_validation_rates():
    c = calibrate(LABELS, PROBS, 0.5)

    assert c["value"] == pytest.approx(0.2)
    assert c["target_pass_rate"] == 0.5
    assert c["val_false_deny_rate"] == pytest.approx(1 / 3)
    assert c["val_detection_rate"] == pytest.approx(1.0)


def test_metrics_with_no_predicted_positives_do_not_divide_by_zero():
    m = classification_metrics(LABELS, torch.zeros(6), 0.5)

    assert m["precision"] == 0.0
    assert m["f1"] == 0.0


def test_hard_negatives_come_from_peers_and_are_never_real_access(graph):
    positives = graph.data[graph.target].edge_index

    hard = sample_hard_negatives(graph, positives, per_positive=2, seed=0)

    real = set(map(tuple, positives.t().tolist()))
    assert hard.size(1) > 0
    for pair in hard.t().tolist():
        assert tuple(pair) not in real
        assert pair[1] in positives[1].tolist()


def test_evaluate_reports_both_negative_kinds(graph):
    result = train(graph, FAST)

    report = evaluate(result.model, graph, result.test_data)

    for name in ["random_negatives", "hard_negatives"]:
        assert report[name]["positives"] == 2
        assert 0.0 <= report[name]["hgnn"]["at_p_0.5"]["auc"] <= 1.0
        assert len(report[name]["hgnn"]["thresholds"]) == 4
        assert 0.0 <= report[name]["peer_coverage"]["auc"] <= 1.0
        assert len(report[name]["combined"]) == 4
        assert report[name]["hgnn"]["calibrated"] == []


def test_evaluate_with_validation_data_adds_calibration_table(graph):
    result = train(graph, FAST)

    report = evaluate(
        result.model, graph, result.test_data,
        val_labels=result.val_labels, val_probs=result.val_probs,
    )

    for name in ["random_negatives", "hard_negatives"]:
        rows = report[name]["hgnn"]["calibrated"]
        assert [r["target_pass_rate"] for r in rows] == list(PASS_RATES)
        thresholds = [r["risk_threshold"] for r in rows]
        assert thresholds == sorted(thresholds)


def test_test_split_is_on_by_default(graph):
    result = train(graph, TrainConfig(hidden=8, max_epochs=3))

    assert result.test_data is not None


def test_test_split_can_be_turned_off(graph):
    result = train(graph, TrainConfig(hidden=8, max_epochs=3, test_ratio=0.0))

    assert result.test_data is None


def test_saved_model_gives_the_same_evaluation(graph, tmp_path):
    result = train(graph, FAST)
    save(result, graph, FAST, tmp_path, data_folder=TOY)
    in_memory = evaluate(result.model, graph, result.test_data,
                         val_labels=result.val_labels, val_probs=result.val_probs)

    model, loaded_graph, split, _ = load_trained(tmp_path)
    reloaded = evaluate(model, loaded_graph, split["test_data"],
                        val_labels=split["val_labels"], val_probs=split["val_probs"])

    assert reloaded == in_memory


def run(*args):
    return subprocess.run(
        [sys.executable, *map(str, args)], capture_output=True, text=True, check=False
    )


def test_command_line_evaluates_without_training(tmp_path):
    trained = run(RUN, "--data", TOY, "--target-relation", "accessed", "--out", tmp_path,
                  "--test-ratio", "0.2", "--hidden", "8", "--max-epochs", "5")
    assert trained.returncode == 0, trained.stderr

    completed = run(SCRIPT, "--model-dir", tmp_path)

    assert completed.returncode == 0, completed.stderr
    assert "early stop" not in completed.stderr and "epoch 10" not in completed.stderr
    assert "hard_negatives" in completed.stdout
    assert "calibrated on validation" in completed.stdout
    assert '"test_metrics"' in (tmp_path / "metadata.json").read_text(encoding="utf-8")


def test_command_line_refuses_a_model_without_test_split(tmp_path):
    trained = run(RUN, "--data", TOY, "--target-relation", "accessed", "--out", tmp_path,
                  "--test-ratio", "0", "--hidden", "8", "--max-epochs", "3")
    assert trained.returncode == 0, trained.stderr

    completed = run(SCRIPT, "--model-dir", tmp_path)

    assert completed.returncode != 0
    assert "--test-ratio 0" in completed.stderr
