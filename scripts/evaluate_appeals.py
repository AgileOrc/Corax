"""Score the appeal pipeline (similar cases + candidate patterns) on scenarios with known answers.

Per scenario with a hidden rule:
    precision@k     share of the k similar cases that belong to the hidden rule
    rank            position of the expected pattern in the candidate list (1 = first)
    top: covered    share of the hidden pairs the first candidate would open
    top: precision  share of the pairs the first candidate opens that belong to the hidden rule
Per one-off scenario (nothing should be generalised): users and pairs the first candidate opens.

Example:
    python scripts/evaluate_appeals.py --model-dir output/mini-campus \
        --scenarios output/mini-campus-data/scenarios.json
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai-corax"))

import appeal_scenarios
from graph import GraphData
from patterns import Candidate, Predicate, candidates
from risk import RiskModel
from similar import SimilarityIndex


@dataclass
class Result:
    name: str
    one_off: bool
    hidden: int
    precision_at_k: float | None
    rank: int | None  # None: the expected pattern is not among the candidates
    candidates: int
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


def coverage(structure, candidate: Candidate, hidden) -> tuple[float, float]:
    """(share of hidden pairs the candidate opens, share of its opened pairs that are hidden)."""
    covered = sum(all(p.holds(structure, u, o) for p in candidate.predicates) for u, o in hidden)
    share = covered / len(hidden) if hidden else 0.0
    precision = covered / candidate.pairs if candidate.pairs else 0.0
    return share, precision


def evaluate(model_dir: Path, scenario_file: Path, k: int, max_per_user: int | None):
    model, graph = RiskModel.load(model_dir), GraphData.load(model_dir)
    index = SimilarityIndex(model)
    scenario_set = appeal_scenarios.load(scenario_file)
    results = []
    for s in scenario_set.scenarios:
        neighbours = [
            (c.user, c.object) for c in index.find(*s.appeal, k, graph.has_access, max_per_user)
        ]
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
        hidden = s.hidden - {s.appeal}
        top = found[0] if found else None
        result = Result(
            name=s.name,
            one_off=s.expected is None,
            hidden=len(hidden),
            precision_at_k=precision_at_k(neighbours, hidden) if hidden else None,
            rank=None,
            candidates=len(found),
            top=top.text() if top else None,
            top_users=top.users if top else None,
            top_pairs=top.pairs if top else None,
            top_covered=None,
            top_precision=None,
        )
        if s.expected is not None:
            result.rank = rank_of(found, tuple(Predicate(**p) for p in s.expected))
        if top and hidden:
            result.top_covered, result.top_precision = coverage(graph.structure, top, hidden)
        results.append(result)
    return results


def print_report(results: list[Result], k: int) -> None:
    def pct(value):
        return "-" if value is None else f"{value:.0%}"

    rules = [r for r in results if not r.one_off]
    print(f"{'scenario':44}{'hidden':>7}{f'P@{k}':>7}{'rank':>6}{'top covers':>12}{'top prec':>10}")
    for r in rules:
        rank = "-" if r.rank is None else str(r.rank)
        print(
            f"{r.name[:43]:44}{r.hidden:>7}{pct(r.precision_at_k):>7}{rank:>6}"
            f"{pct(r.top_covered):>12}{pct(r.top_precision):>10}"
        )
    if rules:
        ranks = [r.rank for r in rules]
        print(
            f"\nmean P@{k} {sum(r.precision_at_k or 0 for r in rules) / len(rules):.0%}   "
            f"expected rule ranked 1st: {sum(x == 1 for x in ranks)}/{len(rules)}   "
            f"in top 3: {sum(x is not None and x <= 3 for x in ranks)}/{len(rules)}   "
            f"not listed: {sum(x is None for x in ranks)}/{len(rules)}"
        )

    one_offs = [r for r in results if r.one_off]
    if one_offs:
        print("\none-off appeals (nothing should generalise): first candidate")
        for r in one_offs:
            if r.top is None:
                print(f"  {r.name:20} no candidate, exact exception only")
            else:
                users = "?" if r.top_users is None else r.top_users
                print(f"  {r.name:20} users {users}, pairs {r.top_pairs}: {r.top}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the appeal pipeline on known scenarios.")
    parser.add_argument("--model-dir", required=True, type=Path, help="folder written by hgnn-job")
    parser.add_argument("--scenarios", required=True, type=Path, help="scenarios.json")
    parser.add_argument("-k", type=int, default=10)
    parser.add_argument("--max-per-user", type=int, default=2, help="0 = no limit")
    parser.add_argument("--out", type=Path, help="also write the results as JSON")
    args = parser.parse_args()

    results = evaluate(args.model_dir, args.scenarios, args.k, args.max_per_user or None)
    print_report(results, args.k)
    if args.out:
        args.out.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
        print(f"\nresults written to {args.out}")


if __name__ == "__main__":
    main()
