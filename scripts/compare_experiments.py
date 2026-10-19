# Compare evaluation results of several HGNN experiments side by side.
# Each folder must contain a metadata.json written by scripts/evaluate_hgnn.py.
    # python scripts/compare_experiments.py output/exp-base output/exp-l1 output/exp-hard50

import argparse
import json
from pathlib import Path


def _row(rows: list[dict], **match) -> dict:
    return next(r for r in rows if all(r[k] == v for k, v in match.items()))


def _calibrated(rnd: dict, hard: dict, pass_rate: float) -> dict:
    # Missing in results from before calibration was added.
    rows_rnd, rows_hard = rnd["hgnn"].get("calibrated", []), hard["hgnn"].get("calibrated", [])
    if not rows_rnd:
        return {"fdr@99%": "-", "det_hard@99%": "-"}
    r = _row(rows_rnd, target_pass_rate=pass_rate)
    h = _row(rows_hard, target_pass_rate=pass_rate)
    return {"fdr@99%": r["false_deny_rate"], "det_hard@99%": h["detection_rate"]}


def summarize(folder: Path) -> dict:
    meta = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    config, metrics = meta["config"], meta["test_metrics"]
    rnd, hard = metrics["random_negatives"], metrics["hard_negatives"]
    return {
        "experiment": folder.name,
        "layers": config.get("num_layers", 2),
        "hidden": config["hidden"],
        "hard_neg": config.get("hard_negative_ratio", 0.0),
        "epochs": meta["epochs_run"],
        "auc_random": rnd["hgnn"]["at_p_0.5"]["auc"],
        "auc_hard": hard["hgnn"]["at_p_0.5"]["auc"],
        "fdr@0.9": _row(hard["hgnn"]["thresholds"], risk_threshold=0.9)["false_deny_rate"],
        "det_hard@0.9": _row(hard["hgnn"]["thresholds"], risk_threshold=0.9)["detection_rate"],
        "det_rand@0.9": _row(rnd["hgnn"]["thresholds"], risk_threshold=0.9)["detection_rate"],
        **_calibrated(rnd, hard, 0.99),
        "cov_auc_hard": hard["peer_coverage"]["auc"],
        "comb_fdr": _row(hard["combined"], min_coverage=0.05)["false_deny_rate"],
        "comb_det_hard": _row(hard["combined"], min_coverage=0.05)["detection_rate"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare HGNN experiment results.")
    parser.add_argument("folders", nargs="+", type=Path)
    args = parser.parse_args()

    rows = [summarize(folder) for folder in args.folders]
    columns = list(rows[0])
    widths = {c: max(len(c), *(len(_fmt(r[c])) for r in rows)) for c in columns}
    print("  ".join(c.ljust(widths[c]) for c in columns))
    for r in rows:
        print("  ".join(_fmt(r[c]).ljust(widths[c]) for c in columns))
    print(
        "\nauc_* = HGNN AUC on random / hard negatives; fdr@0.9 = false deny rate at risk > 0.9;"
        "\ndet_* = detection rate at risk > 0.9;"
        " cov_auc_hard = peer coverage AUC on hard negatives;"
        "\ncomb_* = deny if risk > 0.9 OR fewer than 5% of peers have the object (hard negatives)."
        "\n*@99% = threshold from validation so that 99% of real access passes, measured on test."
    )


def _fmt(value) -> str:
    return f"{value:.4f}" if isinstance(value, float) else str(value)


if __name__ == "__main__":
    main()
