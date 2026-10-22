# Command: python scripts/evaluate/evaluate_hgnn.py --model-dir output/hgnn

import argparse
import json
import logging
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="`torch.jit.script` is deprecated")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hgnn.evaluate import evaluate
from hgnn.export import load_trained


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate a trained HGNN on its held-out test edges (no training)."
    )
    parser.add_argument("--model-dir", required=True, type=Path, help="folder written by python -m hgnn")
    parser.add_argument("--data", help="data folder, if it moved since training")
    return parser.parse_args()

def print_report(results: dict) -> None:
    names = list(results)
    print()
    print(f"{'HGNN':22}" + "".join(f"{n:>20}" for n in names))
    print(f"{'pairs (pos / neg)':22}" + "".join(
        f"{results[n]['positives']:>9} / {results[n]['negatives']:<8}" for n in names
    ))
    for key in ["auc", "precision", "recall", "f1", "accuracy"]:
        label = key if key == "auc" else f"{key} @p=0.5"
        values = "".join(f"{results[n]['hgnn']['at_p_0.5'][key]:>20.4f}" for n in names)
        print(f"{label:22}{values}")
    print(f"{'peer coverage AUC':22}" + "".join(
        f"{results[n]['peer_coverage']['auc']:>20.4f}" for n in names
    ))

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

    model, graph, split, metadata = load_trained(args.model_dir, args.data)
    if "test_data" not in split:
        sys.exit(f"{args.model_dir} was trained with --test-ratio 0; retrain with a test split")

    results = evaluate(
        model, graph, split["test_data"], seed=metadata["config"]["seed"],
        val_labels=split["val_labels"], val_probs=split["val_probs"],
    )
    metadata["test_metrics"] = results
    metadata_path = args.model_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"\nbest epoch {metadata['best_epoch']} of {metadata['epochs_run']}, val AUC {metadata['val_auc']:.4f}")
    print_report(results)
    print_calibration(results)
    chosen = metadata["risk_threshold"]
    print(f"\nexported risk threshold {chosen['value']:.4f} (target pass rate {chosen['target_pass_rate']:.1%})")
    print(f"\ntest metrics added to {metadata_path}")

if __name__ == "__main__":
    main()
