# Shows what the risk score predicts for (user, object) pairs the model never saw during training.
#
# The pairs come from the test split that python -m hgnn held out (--test-ratio > 0). The embeddings are
# computed without those edges, as in scripts/evaluate/evaluate_hgnn.py, so the model cannot have memorised them.
#   allowed      a real access from the test split; the AI should let it pass
#   not allowed  random pair without access; the AI should deny it
#   peer has it  pair without access whose object a peer of the user (same group, e.g. same program) has;
#                the hardest case, because the pair looks normal
# A pair is denied when risk > the threshold in metadata.json, the same rule /risk uses.
#
# python -m hgnn --data output/dummy-data --target-relation accessed --out output/dummy --learning-rate 0.01 --patience 50
# python scripts/demo_risk.py --model-dir output/dummy

import argparse
import random
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="`torch.jit.script` is deprecated")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch

from hgnn.evaluate import sample_hard_negatives
from hgnn.export import load_trained
from hgnn.model import link_probability

KINDS = ("allowed", "not allowed", "peer has it")


def score(model_dir: Path, seed: int = 0) -> tuple[list[dict], float]:
    model, graph, split, metadata = load_trained(model_dir)
    if "test_data" not in split:
        raise ValueError(f"{model_dir} was trained with --test-ratio 0; retrain with a test split to run the demo")
    test_data, target = split["test_data"], graph.target
    with torch.no_grad():
        h = model.encode(test_data)

    pairs, labels = test_data[target].edge_label_index, test_data[target].edge_label
    positives = pairs[:, labels == 1]
    groups = [
        ("allowed", positives),
        ("not allowed", pairs[:, labels == 0]),
        ("peer has it", sample_hard_negatives(graph, positives, per_positive=1, seed=seed)),
    ]

    threshold = metadata["risk_threshold"]["value"]
    users, objects = graph.node_ids[target[0]], graph.node_ids[target[2]]
    rows = []
    for kind, group in groups:
        with torch.no_grad():
            probs = link_probability(h[target[0]], h[target[2]], group)
        for (u, o), p in zip(group.t().tolist(), probs.tolist(), strict=True):
            risk = 1 - p
            denied = risk > threshold
            rows.append({"kind": kind, "user": users[u], "object": objects[o], "risk": risk, "denied": denied, "correct": denied == (kind != "allowed")})
    return rows, threshold


def print_demo(rows: list[dict], threshold: float, show: int, seed: int) -> None:
    rng = random.Random(seed)
    print(f"{'pair':58}{'truth':>13}{'risk':>8}  AI says")
    for kind in KINDS:
        group = [r for r in rows if r["kind"] == kind]
        for r in rng.sample(group, min(show, len(group))):
            pair = f"{r['user']} -> {r['object']}"
            verdict = "deny" if r["denied"] else "allow"
            print(f"{pair[:57]:58}{kind:>13}{r['risk']:>8.3f}  {verdict:6}{'✓' if r['correct'] else '✗'}")
        print()

    print(f"threshold {threshold:.3f}; all held-out pairs, none seen during training:")
    for kind in KINDS:
        group = [r for r in rows if r["kind"] == kind]
        if group:
            correct = sum(r["correct"] for r in group)
            action = "let through" if kind == "allowed" else "denied"
            print(f"  {kind:12} {correct}/{len(group)} {action} ({correct / len(group):.0%})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Show the risk score on held-out pairs the model never saw, next to the true answer.")
    parser.add_argument("--model-dir", required=True, type=Path, help="folder written by python -m hgnn with a test split")
    parser.add_argument("--show", type=int, default=5, help="example pairs per kind")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    try:
        rows, threshold = score(args.model_dir, args.seed)
    except ValueError as error:
        parser.error(str(error))
    print_demo(rows, threshold, args.show, args.seed)


if __name__ == "__main__":
    # Windows consoles default to cp1252, which cannot print ✓ and ✗
    sys.stdout.reconfigure(encoding="utf-8")
    main()
