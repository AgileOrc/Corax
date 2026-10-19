"""Train the HGNN with a held-out test split and report precision, recall, F1, AUC and thresholds.

The test edges are never used for training or early stopping, so these numbers are honest.
Embeddings are exported as well, and the metrics are added to metadata.json ("test_metrics").

Example:
 """

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

# Third-party deprecation noise (torch / PyG on Python 3.13), not an error in Corax.
warnings.filterwarnings("ignore", message="`torch.jit.script` is deprecated")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hgnn-job"))

from corax_hgnn.evaluate import evaluate  # noqa: E402
from corax_hgnn.export import save  # noqa: E402
from corax_hgnn.graph import load_graph  # noqa: E402
from corax_hgnn.train import TrainConfig, train  # noqa: E402


def parse_args() -> argparse.Namespace:
    defaults = TrainConfig()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", required=True, help="folder with nodes.csv and edges.csv")
    parser.add_argument("--target-relation", required=True)
    parser.add_argument("--out", default="output/hgnn-eval")
    parser.add_argument("--test-ratio", type=float, default=0.1)
    parser.add_argument("--hidden", type=int, default=defaults.hidden)
    parser.add_argument("--num-layers", type=int, default=defaults.num_layers)
    parser.add_argument("--hard-negative-ratio", type=float, default=defaults.hard_negative_ratio)
    parser.add_argument(
        "--target-pass-rate", type=float, default=defaults.target_pass_rate,
        help="share of real access that must pass; sets the exported risk threshold",
    )  # fmt: skip
    parser.add_argument("--learning-rate", type=float, default=defaults.learning_rate)
    parser.add_argument("--max-epochs", type=int, default=defaults.max_epochs)
    parser.add_argument("--patience", type=int, default=defaults.patience)
    parser.add_argument("--seed", type=int, default=defaults.seed)
    return parser.parse_args()


def print_report(results: dict) -> None:
    names = list(results)
    print()
    print(f"{'HGNN':22}" + "".join(f"{n:>20}" for n in names))
    print(f"{'pairs (pos / neg)':22}" + "".join(
        f"{results[n]['positives']:>9} / {results[n]['negatives']:<8}" for n in names
    ))  # fmt: skip
    for key in ["auc", "precision", "recall", "f1", "accuracy"]:
        label = key if key == "auc" else f"{key} @p=0.5"
        values = "".join(f"{results[n]['hgnn']['at_p_0.5'][key]:>20.4f}" for n in names)
        print(f"{label:22}{values}")
    print(f"{'peer coverage AUC':22}" + "".join(
        f"{results[n]['peer_coverage']['auc']:>20.4f}" for n in names
    ))  # fmt: skip

    for name in names:
        r = results[name]
        print(f"\n{name}                          false deny   detection")
        for row in r["hgnn"]["thresholds"]:
            print(f"  hgnn risk > {row['risk_threshold']:.1f}{_rates(row)}")
        for row in r["peer_coverage"]["thresholds"]:
            print(f"  peer coverage < {row['min_coverage']:.2f}{_rates(row, 4)}")
        for row in r["combined"]:
            print(f"  risk > {row['risk_threshold']:.1f} or cov < {row['min_coverage']:.2f}"
                  f"{_rates(row, 0)}")  # fmt: skip


def print_calibration(results: dict) -> None:
    """Threshold chosen on validation data, checked on the test edges."""
    rnd = results["random_negatives"]["hgnn"]["calibrated"]
    hard = results["hard_negatives"]["hgnn"]["calibrated"]
    print("\ncalibrated on validation, measured on test (deny when risk > threshold)")
    print(f"{'target pass':>12}{'threshold':>11}{'false deny':>12}{'detect random':>15}"
          f"{'detect hard':>13}")  # fmt: skip
    for r, h in zip(rnd, hard, strict=True):
        print(
            f"{r['target_pass_rate']:>12.1%}{r['risk_threshold']:>11.4f}"
            f"{r['false_deny_rate']:>12.4f}{r['detection_rate']:>15.4f}{h['detection_rate']:>13.4f}"
        )


def _rates(row: dict, pad: int = 8) -> str:
    return f"{'':{pad}}{row['false_deny_rate']:>17.4f}{row['detection_rate']:>12.4f}"


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    graph = load_graph(args.data, args.target_relation)
    config = TrainConfig(
        hidden=args.hidden,
        num_layers=args.num_layers,
        hard_negative_ratio=args.hard_negative_ratio,
        target_pass_rate=args.target_pass_rate,
        learning_rate=args.learning_rate,
        max_epochs=args.max_epochs,
        patience=args.patience,
        test_ratio=args.test_ratio,
        seed=args.seed,
    )
    result = train(graph, config)
    out_dir = save(result, graph, config, args.out)

    results = evaluate(
        result.model, graph, result.test_data, seed=args.seed,
        val_labels=result.val_labels, val_probs=result.val_probs,
    )  # fmt: skip
    metadata_path = out_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["test_metrics"] = results
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(
        f"\nbest epoch {result.best_epoch} of {len(result.history)}, val AUC {result.val_auc:.4f}"
    )
    print_report(results)
    print_calibration(results)
    chosen = metadata["risk_threshold"]
    print(
        f"\nexported risk threshold {chosen['value']:.4f}"
        f" (target pass rate {chosen['target_pass_rate']:.1%})"
    )
    print(f"\nsaved to {out_dir} (test metrics in metadata.json)")


if __name__ == "__main__":
    main()
