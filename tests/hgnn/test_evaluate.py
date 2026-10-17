import subprocess
import sys
from pathlib import Path

import pytest
import torch
from corax_hgnn.evaluate import (
    classification_metrics,
    confusion,
    evaluate,
    sample_hard_negatives,
    threshold_table,
)
from corax_hgnn.graph import load_graph
from corax_hgnn.train import TrainConfig, train

TOY = Path(__file__).parent / "fixtures" / "toy_graph"
SCRIPT = Path(__file__).parents[2] / "scripts" / "evaluate_hgnn.py"
FAST = TrainConfig(hidden=16, learning_rate=0.01, max_epochs=50, patience=5, test_ratio=0.2)

# labels: 3 real access (1), 3 negatives (0); probs from a pretend model
LABELS = torch.tensor([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
PROBS = torch.tensor([0.9, 0.8, 0.4, 0.6, 0.2, 0.1])


@pytest.fixture
def graph():
    return load_graph(TOY, "accessed")


# --- metrics on a hand-checked example ---------------------------------------


def test_confusion_matrix():
    # p >= 0.5: predicted access for 0.9, 0.8 (real) and 0.6 (negative)
    assert confusion(LABELS, PROBS, 0.5) == {"tp": 2, "fp": 1, "tn": 2, "fn": 1}


def test_precision_recall_f1_accuracy():
    m = classification_metrics(LABELS, PROBS, 0.5)

    assert m["precision"] == pytest.approx(2 / 3)
    assert m["recall"] == pytest.approx(2 / 3)
    assert m["f1"] == pytest.approx(2 / 3)
    assert m["accuracy"] == pytest.approx(4 / 6)


def test_threshold_table_false_deny_and_detection():
    # risk = 1 - p = [0.1, 0.2, 0.6 | 0.4, 0.8, 0.9]
    row = threshold_table(LABELS, PROBS, risk_thresholds=(0.5,))[0]

    assert row["false_deny_rate"] == pytest.approx(1 / 3)  # the real access with p=0.4
    assert row["detection_rate"] == pytest.approx(2 / 3)  # negatives with p=0.2 and 0.1


def test_metrics_with_no_predicted_positives_do_not_divide_by_zero():
    m = classification_metrics(LABELS, torch.zeros(6), 0.5)

    assert m["precision"] == 0.0
    assert m["f1"] == 0.0


# --- hard negatives -------------------------------------------------------------


def test_hard_negatives_come_from_peers_and_are_never_real_access(graph):
    positives = graph.data[graph.target].edge_index

    hard = sample_hard_negatives(graph, positives, per_positive=2, seed=0)

    real = set(map(tuple, positives.t().tolist()))
    assert hard.size(1) > 0
    for pair in hard.t().tolist():
        assert tuple(pair) not in real
        # the object must be owned by someone, i.e. it looks plausible
        assert pair[1] in positives[1].tolist()


# --- evaluation end to end ---------------------------------------------------


def test_evaluate_reports_both_negative_kinds(graph):
    result = train(graph, FAST)

    report = evaluate(result.model, graph, result.test_data)

    for name in ["random_negatives", "hard_negatives"]:
        assert report[name]["positives"] == 2  # 20% of the 10 "accessed" edges
        assert 0.0 <= report[name]["hgnn"]["at_p_0.5"]["auc"] <= 1.0
        assert len(report[name]["hgnn"]["thresholds"]) == 4
        assert 0.0 <= report[name]["peer_coverage"]["auc"] <= 1.0
        assert len(report[name]["combined"]) == 4


def test_no_test_split_by_default(graph):
    result = train(graph, TrainConfig(hidden=8, max_epochs=3))

    assert result.test_data is None


def test_command_line_writes_test_metrics(tmp_path):
    completed = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--data", str(TOY),
            "--target-relation", "accessed",
            "--out", str(tmp_path),
            "--test-ratio", "0.2",
            "--hidden", "8",
            "--max-epochs", "5",
        ],
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip

    assert completed.returncode == 0, completed.stderr
    assert "hard_negatives" in completed.stdout
    assert '"test_metrics"' in (tmp_path / "metadata.json").read_text(encoding="utf-8")
