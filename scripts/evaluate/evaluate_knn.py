# Scores the appeal pipeline (kNN similar cases + candidate patterns + tier) on scenarios with known answers.
# It only loads models trained by python -m hgnn; it never trains.
#
# Per scenario with a hidden rule:
#   P@k            share of the k similar cases that belong to the hidden rule
#   rank           first candidate that opens exactly the hidden pairs (equivalent to the rule)
#   rank_expected  candidate whose predicates are the expected ones (as written in scenarios.json)
#   tier           small / large for that candidate (small = applied without admin confirmation)
#   top covers     share of the hidden pairs the first candidate would open
#   top prec       share of the pairs the first candidate opens that belong to the hidden rule
# Per one-off scenario (nothing should be generalised): the first candidate and its tier.
#
# One model:   python scripts/evaluate/evaluate_knn.py --model-dir output/amazon-appeals --scenarios datasets/amazon-appeals/scenarios.json
# Many models: python scripts/evaluate/evaluate_knn.py --runs "output/xu-stoller/*/rule_*"
#              (each run folder holds model/ from python -m hgnn and data/scenarios.json from a prepare script)

import argparse
import glob
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "service"), str(ROOT / "scripts" / "prepare")]

import appeal_scenarios
from graph import GraphData
from patterns import Candidate, Predicate, candidates, opened_pairs
from risk import RiskModel
from similar import SimilarityIndex
from tier import TierLimits, assess


@dataclass
class Result:
    run: str
    name: str
    one_off: bool
    hidden: int
    precision_at_k: float | None
    rank: int | None
    rank_expected: int | None
    candidates: int
    tier: str | None
    tier_reasons: list[str]
    top: str | None
    top_users: int | None
    top_pairs: int | None
    top_covered: float | None
    top_precision: float | None


def precision_at_k(neighbours, hidden) -> float:
    return sum(pair in hidden for pair in neighbours) / len(neighbours) if neighbours else 0.0


def rank_of(found: list[Candidate], expected: tuple[Predicate, ...]) -> int | None:
    wanted = set(expected)
    for position, candidate in enumerate(found, start=1):
        if set(candidate.predicates) == wanted:
            return position
    return None


def rank_by_pairs(found: list[Candidate], hidden, opened) -> int | None:
    for position, candidate in enumerate(found, start=1):
        if not candidate.estimated and candidate.pairs == len(hidden) and set(opened(candidate)) == hidden:
            return position
    return None


def coverage(structure, candidate: Candidate, hidden) -> tuple[float, float]:
    covered = sum(all(p.holds(structure, u, o) for p in candidate.predicates) for u, o in hidden)
    share = covered / len(hidden) if hidden else 0.0
    precision = covered / candidate.pairs if candidate.pairs else 0.0
    return share, precision


def evaluate(model_dir: Path, scenario_file: Path, k: int, max_per_user: int | None, limits: TierLimits, run: str = "") -> list[Result]:
    model, graph = RiskModel.load(model_dir), GraphData.load(model_dir)
    index = SimilarityIndex(model)
    scenario_set = appeal_scenarios.load(scenario_file)
    results = []
    for s in scenario_set.scenarios:
        neighbours = [(c.user, c.object) for c in index.find(*s.appeal, k, graph.has_access, max_per_user)]
        found = candidates(
            graph.structure,
            graph.access,
            s.appeal,
            index.user_ids,
            index.object_ids,
            neighbours=neighbours,
            object_identity=scenario_set.object_identity,
            object_values=scenario_set.object_values,
            max_size=scenario_set.max_size,
        )

        def opened(candidate, appeal=s.appeal):
            try:
                return opened_pairs(graph.structure, graph.access, appeal, index.user_ids, index.object_ids, candidate.predicates)
            except ValueError:
                return None

        hidden = s.hidden - {s.appeal}
        top = found[0] if found else None
        rank = rank_by_pairs(found, hidden, lambda c: opened(c) or ()) if hidden else None
        rank_expected = rank_of(found, tuple(Predicate(**p) for p in s.expected)) if s.expected else None
        chosen_rank = rank or rank_expected
        chosen = found[chosen_rank - 1] if chosen_rank else (top if s.expected is None else None)
        pairs = opened(chosen) if chosen else None
        scope = assess(pairs, model, limits) if pairs is not None else None
        covered, precision = coverage(graph.structure, top, hidden) if top and hidden else (None, None)
        results.append(
            Result(
                run=run,
                name=s.name,
                one_off=s.expected is None,
                hidden=len(hidden),
                precision_at_k=precision_at_k(neighbours, hidden) if hidden else None,
                rank=rank,
                rank_expected=rank_expected,
                candidates=len(found),
                tier=scope.tier if scope else None,
                tier_reasons=list(scope.reasons) if scope else [],
                top=top.text() if top else None,
                top_users=top.users if top else None,
                top_pairs=top.pairs if top else None,
                top_covered=covered,
                top_precision=precision,
            )
        )
    return results


def summary(label: str, ranks: list[int | None]) -> str:
    n = len(ranks)
    return (
        f"{label}: rank 1 {sum(x == 1 for x in ranks)}/{n}, top 3 {sum(x is not None and x <= 3 for x in ranks)}/{n}, "
        f"top 5 {sum(x is not None and x <= 5 for x in ranks)}/{n}, listed {sum(x is not None for x in ranks)}/{n}"
    )


def print_report(results: list[Result], k: int) -> None:
    def pct(value):
        return "-" if value is None else f"{value:.0%}"

    def num(value):
        return "-" if value is None else str(value)

    rules = [r for r in results if not r.one_off]
    if rules:
        print(f"{'scenario':48}{'hidden':>7}{f'P@{k}':>7}{'rank':>6}{'rank_exp':>9}{'cands':>7}{'tier':>7}{'top covers':>12}{'top prec':>10}")
        for r in rules:
            name = f"{r.run} {r.name}".strip()
            print(
                f"{name[:47]:48}{r.hidden:>7}{pct(r.precision_at_k):>7}{num(r.rank):>6}{num(r.rank_expected):>9}"
                f"{r.candidates:>7}{num(r.tier):>7}{pct(r.top_covered):>12}{pct(r.top_precision):>10}"
            )
        print(f"\n{len(rules)} appeals, mean P@{k} {sum(r.precision_at_k or 0 for r in rules) / len(rules):.0%}")
        print("  " + summary("candidate opening exactly the hidden pairs", [r.rank for r in rules]))
        print("  " + summary("candidate with the expected predicates   ", [r.rank_expected for r in rules]))
        tiers = [r.tier for r in rules if r.tier]
        print(f"  tier of the correct rule: small {tiers.count('small')}, large {tiers.count('large')}")

        by_name: dict[str, list[Result]] = {}
        for r in rules:
            by_name.setdefault(r.name, []).append(r)
        if any(len(items) > 1 for items in by_name.values()):
            print("\nper scenario name (over runs):")
            for name, items in sorted(by_name.items()):
                ranks = [x.rank or x.rank_expected for x in items]
                print(
                    f"  {name:24} P@{k} {sum(x.precision_at_k or 0 for x in items) / len(items):4.0%}, "
                    f"rank 1 {sum(x == 1 for x in ranks)}/{len(items)}, top 5 {sum(x is not None and x <= 5 for x in ranks)}/{len(items)}"
                )

    one_offs = [r for r in results if r.one_off]
    if one_offs:
        print("\none-off appeals (nothing should generalise): first candidate")
        for r in one_offs:
            name = f"{r.run} {r.name}".strip()
            if r.top is None:
                print(f"  {name:24} no candidate, exact exception only")
            else:
                users = "?" if r.top_users is None else r.top_users
                print(f"  {name:24} {num(r.tier)}, users {users}, pairs {r.top_pairs}: {r.top}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Score kNN similar cases and candidate patterns on saved models (no training).")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--model-dir", type=Path, help="folder written by python -m hgnn (needs --scenarios)")
    source.add_argument("--runs", help="glob of run folders, each with model/ and data/scenarios.json")
    parser.add_argument("--scenarios", type=Path, help="scenarios.json for --model-dir")
    parser.add_argument("-k", type=int, default=10)
    parser.add_argument("--max-per-user", type=int, default=2, help="0 = no limit")
    parser.add_argument("--max-user-share", type=float, default=TierLimits.max_user_share)
    parser.add_argument("--max-pairs", type=int, default=TierLimits.max_pairs)
    parser.add_argument("--max-mean-risk", type=float, default=TierLimits.max_mean_risk)
    parser.add_argument("--out", type=Path, help="also write the results as JSON")
    args = parser.parse_args()

    if args.model_dir:
        if not args.scenarios:
            parser.error("--model-dir needs --scenarios")
        jobs = [(args.model_dir, args.scenarios, "")]
    else:
        runs = sorted(Path(p) for p in glob.glob(args.runs) if (Path(p) / "model" / "embeddings.npz").exists())
        if not runs:
            parser.error(f"no run folder with model/embeddings.npz matches {args.runs}")
        jobs = [(run / "model", run / "data" / "scenarios.json", f"{run.parent.name}/{run.name}") for run in runs]

    limits = TierLimits(args.max_user_share, args.max_pairs, args.max_mean_risk)
    results = []
    for model_dir, scenario_file, run in jobs:
        results += evaluate(model_dir, scenario_file, args.k, args.max_per_user or None, limits, run)
    print_report(results, args.k)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
        print(f"\nresults written to {args.out}")


if __name__ == "__main__":
    main()
