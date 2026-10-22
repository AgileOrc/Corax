# Leave-one-rule-out evaluation of the appeal pipeline on Xu & Stoller ABAC policies.
#
# For every .abac file and every rule: hide the pairs only that rule grants, train the HGNN on the rest, appeal one
# hidden pair, and check whether the similar cases and the candidate patterns lead back to the hidden rule.
#
#   P@k          share of the k similar cases that belong to the hidden rule
#   rank         position of the first candidate that opens exactly the hidden pairs (equivalent to the rule)
#   rank_exact   position of the candidate whose predicates are the rule's own translation
#
# Command: python scripts/evaluate_xu_stoller.py --files "datasets/xu-stoller/ABACMining/gen-case-studies/university/university-sets_10_*.abac"

import argparse
import glob
import json
import logging
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "hgnn-job"), str(ROOT / "ai-corax"), str(ROOT / "scripts")]
warnings.filterwarnings("ignore", message="`torch.jit.script` is deprecated")

import appeal_scenarios
import convert_xu_stoller
from corax_hgnn.export import save, save_graph
from corax_hgnn.graph import load_graph
from corax_hgnn.train import TrainConfig, train
from graph import GraphData
from patterns import Predicate, candidates, opened_pairs
from risk import RiskModel
from similar import SimilarityIndex

DEFAULT_FILES = "datasets/xu-stoller/ABACMining/gen-case-studies/university/university-sets_10_*.abac"


def run_one(source: Path, rule: int, out: Path, args) -> dict:
    policy = convert_xu_stoller.parse(source.read_text(encoding="utf-8"))
    data_dir, model_dir = out / "data", out / "model"
    summary = convert_xu_stoller.write(data_dir, policy, rule, args.seed)
    record = {"file": source.name, "rule": rule, "text": summary["rule"], "hidden": summary["hidden"],
              "expressible": summary["expressible"]}
    if not summary["hidden"]:
        return {**record, "skipped": "no pair is granted by this rule alone"}

    started = time.time()
    graph = load_graph(data_dir, convert_xu_stoller.TARGET)
    config = TrainConfig(learning_rate=args.learning_rate, patience=args.patience, max_epochs=args.max_epochs,
                         test_ratio=0.0, seed=args.seed)
    result = train(graph, config)
    save(result, graph, config, model_dir, data_folder=data_dir)
    save_graph(data_dir, convert_xu_stoller.TARGET, model_dir)

    scenario = appeal_scenarios.load(data_dir / "scenarios.json").scenarios[0]
    model, graph_data = RiskModel.load(model_dir), GraphData.load(model_dir)
    index = SimilarityIndex(model)
    hidden = scenario.hidden - {scenario.appeal}
    neighbours = [(c.user, c.object) for c in index.find(*scenario.appeal, args.k, graph_data.has_access, args.max_per_user)]
    found = candidates(graph_data.structure, graph_data.access, scenario.appeal, index.user_ids, index.object_ids,
                       neighbours=neighbours, max_size=3, object_values=True)

    expected = set(Predicate(**p) for p in scenario.expected) if scenario.expected else None
    rank_exact = next((i for i, c in enumerate(found, 1) if expected and set(c.predicates) == expected), None)
    rank = None
    for i, c in enumerate(found, 1):
        if c.pairs == len(hidden):
            opened = set(opened_pairs(graph_data.structure, graph_data.access, scenario.appeal,
                                      index.user_ids, index.object_ids, c.predicates))
            if opened == hidden:
                rank = i
                break
    return {
        **record,
        "val_auc": round(result.val_auc, 4),
        "p_at_k": sum(n in hidden for n in neighbours) / len(neighbours) if neighbours else 0.0,
        "rank": rank,
        "rank_exact": rank_exact,
        "candidates": len(found),
        "top": found[0].text() if found else None,
        "seconds": round(time.time() - started, 1),
    }


def show(rows: list[dict], k: int) -> None:
    def fmt(value):
        return "-" if value is None else str(value)

    print(f"\n{'file':26}{'rule':>5}{'hidden':>8}{f'P@{k}':>7}{'rank':>6}{'exact':>7}{'cands':>7}  rule text")
    for r in rows:
        if "skipped" in r:
            print(f"{r['file'][:25]:26}{r['rule']:>5}{r['hidden']:>8}{'':>7}{'':>6}{'':>7}{'':>7}  skipped: {r['skipped']}")
            continue
        print(f"{r['file'][:25]:26}{r['rule']:>5}{r['hidden']:>8}{r['p_at_k']:>7.0%}{fmt(r['rank']):>6}"
              f"{fmt(r['rank_exact']):>7}{r['candidates']:>7}  {r['text'][5:-1]}")

    done = [r for r in rows if "skipped" not in r]
    if not done:
        return
    ranks = [r["rank"] for r in done]
    print(f"\n{len(done)} appeals: mean P@{k} {sum(r['p_at_k'] for r in done) / len(done):.0%}, "
          f"rule found at rank 1: {sum(x == 1 for x in ranks)}/{len(done)}, "
          f"in top 3: {sum(x is not None and x <= 3 for x in ranks)}/{len(done)}, "
          f"listed at all: {sum(x is not None for x in ranks)}/{len(done)}")
    by_rule: dict[int, list] = {}
    for r in done:
        by_rule.setdefault(r["rule"], []).append(r)
    print("\nper rule (over files):")
    for rule, items in sorted(by_rule.items()):
        rk = [x["rank"] for x in items]
        print(f"  rule {rule:2}: P@{k} {sum(x['p_at_k'] for x in items) / len(items):.0%}, "
              f"rank 1 {sum(x == 1 for x in rk)}/{len(items)}, top 3 {sum(x is not None and x <= 3 for x in rk)}/{len(items)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Leave-one-rule-out appeal evaluation on Xu & Stoller policies.")
    parser.add_argument("--files", default=DEFAULT_FILES, help="glob of .abac files")
    parser.add_argument("--rules", type=int, nargs="*", help="rule numbers (default: all)")
    parser.add_argument("--out", type=Path, default=Path("output/xu-stoller"))
    parser.add_argument("-k", type=int, default=10)
    parser.add_argument("--max-per-user", type=int, default=2)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--patience", type=int, default=50)
    parser.add_argument("--max-epochs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    files = sorted(Path(f) for f in glob.glob(args.files))
    if not files:
        parser.error(f"no .abac files match {args.files}")
    rows = []
    for source in files:
        policy = convert_xu_stoller.parse(source.read_text(encoding="utf-8"))
        for rule in args.rules or [r.index for r in policy.rules]:
            row = run_one(source, rule, args.out / source.stem / f"rule_{rule:02d}", args)
            rows.append(row)
            state = row.get("skipped") or f"P@{args.k} {row['p_at_k']:.0%}, rank {row['rank']}, {row['seconds']}s"
            print(f"{source.name} rule {rule}: {state}", flush=True)

    show(rows, args.k)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nresults written to {args.out / 'results.json'}")


if __name__ == "__main__":
    main()
