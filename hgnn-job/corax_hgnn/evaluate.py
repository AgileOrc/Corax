"""Measure how well the trained HGNN separates real access from unusual access.

Two kinds of negative pairs are used:
- random negatives: a random object the user is not connected to.
- hard negatives:an object that a *peer* has (someone sharing a department, title, manager, program, ...) but this user does not. These look plausible from the outside, which is closer to a real misuse case.

Metrics at a probability threshold (p >= threshold means "looks normal"):
    precision = TP / (TP + FP)      recall = TP / (TP + FN)
    F1 = 2 · precision · recall / (precision + recall)      accuracy = (TP + TN) / all

Corax denies a policy-allowed request when risk = 1 - p is above AI_RISK_THRESHOLD, so the
threshold table reports, for each risk threshold:
    false deny rate = share of real access that would be denied   (should be very low)
    detection rate  = share of negatives that would be denied     (higher is better)

Calibration: the threshold is chosen on validation data so that a target share of real access
passes (e.g. 99%), then checked on the test edges for several targets (PASS_RATES).
"""  # noqa: E501

import random

import torch
from torch import Tensor

from corax_hgnn.graph import Graph
from corax_hgnn.model import HGNN, link_probability
from corax_hgnn.peers import PeerIndex
from corax_hgnn.train import roc_auc

RISK_THRESHOLDS = (0.3, 0.5, 0.7, 0.9)
# deny when fewer than this share of the user's peers have the object
COVERAGE_THRESHOLDS = (0.01, 0.05, 0.1, 0.2)
COMBINED_RISK_THRESHOLD = 0.9
# target shares of real access that pass, for the calibration table
PASS_RATES = (0.95, 0.98, 0.99, 0.995, 0.999)


def confusion(labels: Tensor, probs: Tensor, threshold: float = 0.5) -> dict[str, int]:
    predicted = probs >= threshold
    actual = labels == 1
    return {
        "tp": int((predicted & actual).sum()),
        "fp": int((predicted & ~actual).sum()),
        "tn": int((~predicted & ~actual).sum()),
        "fn": int((~predicted & actual).sum()),
    }


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def classification_metrics(labels: Tensor, probs: Tensor, threshold: float = 0.5) -> dict:
    c = confusion(labels, probs, threshold)
    precision = _ratio(c["tp"], c["tp"] + c["fp"])
    recall = _ratio(c["tp"], c["tp"] + c["fn"])
    return {
        **c,
        "precision": precision,
        "recall": recall,
        "f1": _ratio(2 * precision * recall, precision + recall),
        "accuracy": _ratio(c["tp"] + c["tn"], labels.numel()),
        "auc": roc_auc(labels, probs),
    }


def threshold_table(labels: Tensor, probs: Tensor, risk_thresholds=RISK_THRESHOLDS) -> list[dict]:
    risk = 1 - probs
    positives, negatives = labels == 1, labels == 0
    rows = []
    for t in risk_thresholds:
        denied = risk > t
        rows.append(
            {
                "risk_threshold": t,
                "false_deny_rate": _ratio(int((denied & positives).sum()), int(positives.sum())),
                "detection_rate": _ratio(int((denied & negatives).sum()), int(negatives.sum())),
            }
        )
    return rows


def deny_rates(labels: Tensor, denied: Tensor) -> dict[str, float]:
    positives, negatives = labels == 1, labels == 0
    return {
        "false_deny_rate": _ratio(int((denied & positives).sum()), int(positives.sum())),
        "detection_rate": _ratio(int((denied & negatives).sum()), int(negatives.sum())),
    }


def calibrate_threshold(labels: Tensor, probs: Tensor, target_pass_rate: float) -> float:
    """Risk threshold that lets at least `target_pass_rate` of the real access through.

    Corax denies when risk > threshold, so the threshold is that quantile of the positives' risk.
    Use validation data, never the test edges.
    """
    risk = 1 - probs[labels == 1].double()
    return torch.quantile(risk, target_pass_rate, interpolation="higher").item()


def calibrate(labels: Tensor, probs: Tensor, target_pass_rate: float) -> dict:
    """Calibrated threshold plus its false deny and detection rate on the same (validation) data."""
    threshold = calibrate_threshold(labels, probs, target_pass_rate)
    rates = deny_rates(labels, 1 - probs > threshold)
    return {
        "value": threshold,
        "target_pass_rate": target_pass_rate,
        "val_false_deny_rate": rates["false_deny_rate"],
        "val_detection_rate": rates["detection_rate"],
    }


def sample_hard_negatives(
    graph: Graph, positives: Tensor, per_positive: int = 2, seed: int = 0
) -> Tensor:
    """For each positive (user, object), objects that one of the user's peers has.

    Pairs that are real target edges (including test edges) are never returned.
    """
    index = PeerIndex(graph, graph.data[graph.target].edge_index)
    return index.hard_negatives(positives[0].tolist(), per_positive, random.Random(seed))


def evaluate(
    model: HGNN,
    graph: Graph,
    test_data,
    seed: int = 0,
    val_labels: Tensor | None = None,
    val_probs: Tensor | None = None,
) -> dict:
    """Evaluate on held-out test edges, with random and with hard negatives.

    Three detectors are compared:
      hgnn           deny when risk = 1 - p is above a threshold
      peer_coverage  deny when fewer than a share of the user's peers have the object
      combined       deny when either says so (risk > 0.9 OR coverage below the share)

    With validation labels and probabilities, "hgnn" also gets a "calibrated" table:
    one row per PASS_RATES target, with the threshold chosen on validation data.
    """
    calibrated = []
    if val_labels is not None and val_probs is not None:
        calibrated = [(r, calibrate_threshold(val_labels, val_probs, r)) for r in PASS_RATES]

    target = graph.target
    model.eval()
    with torch.no_grad():
        h = model.encode(test_data)  # test edges are not part of the message graph here
    h_src, h_dst = h[target[0]], h[target[2]]

    pairs = test_data[target].edge_label_index
    labels = test_data[target].edge_label.float()
    positives = pairs[:, labels == 1]

    hard = sample_hard_negatives(graph, positives, seed=seed)
    hard_pairs = torch.cat([positives, hard], dim=1)
    hard_labels = torch.cat([torch.ones(positives.size(1)), torch.zeros(hard.size(1))])

    # Peer coverage may only use what the system can see at test time (not the test edges).
    visible = PeerIndex(graph, test_data[target].edge_index)

    results = {}
    for name, p, y in [
        ("random_negatives", pairs, labels),
        ("hard_negatives", hard_pairs, hard_labels),
    ]:
        with torch.no_grad():
            probs = link_probability(h_src, h_dst, p)
        coverage = visible.coverage(p)
        results[name] = {
            "positives": int(y.sum()),
            "negatives": int((y == 0).sum()),
            "hgnn": {
                "at_p_0.5": classification_metrics(y, probs, 0.5),
                "thresholds": threshold_table(y, probs),
                "calibrated": [
                    {"target_pass_rate": r, "risk_threshold": t, **deny_rates(y, 1 - probs > t)}
                    for r, t in calibrated
                ],
            },
            "peer_coverage": {
                "auc": roc_auc(y, coverage),
                "thresholds": [
                    {"min_coverage": c, **deny_rates(y, coverage < c)} for c in COVERAGE_THRESHOLDS
                ],
            },
            "combined": [
                {
                    "risk_threshold": COMBINED_RISK_THRESHOLD,
                    "min_coverage": c,
                    **deny_rates(y, (1 - probs > COMBINED_RISK_THRESHOLD) | (coverage < c)),
                }
                for c in COVERAGE_THRESHOLDS
            ],
        }
    return results
