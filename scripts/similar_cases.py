"""Print the pairs most similar to an appealed (user, object) pair and the candidate patterns.

With --pick N, also show what choosing candidate N would do: its tier, the Rego for the rule and
the exception, and the validation result. Nothing is written.

Example:
    python scripts/similar_cases.py --model-dir output/toy \
        --user lecturer_budi --object student_candra
    python scripts/similar_cases.py --model-dir output/mini-campus \
        --user lecturer_head_P0 --object student_P0_05 --pick 3 --opa ../opa.exe
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai-corax"))

from graph import GraphData
from patterns import candidates, opened_pairs
from risk import RiskModel
from rules import render_exception, render_rule
from similar import SimilarityIndex
from tier import assess
from validate import expected_decisions, validate


def main() -> None:
    parser = argparse.ArgumentParser(description="Show similar cases and candidate patterns.")
    parser.add_argument("--model-dir", required=True, help="folder written by hgnn-job")
    parser.add_argument("--user", required=True)
    parser.add_argument("--object", required=True)
    parser.add_argument("-k", type=int, default=10)
    parser.add_argument("--max-per-user", type=int, default=2, help="0 = no limit")
    parser.add_argument("--candidates", type=int, default=8, help="how many candidates to show")
    parser.add_argument("--object-values", action="store_true", help="allow object_has predicates")
    parser.add_argument("--object-identity", action="store_true", help="allow object_is (Amazon)")
    parser.add_argument("--pick", type=int, help="show tier, Rego and validation for candidate N")
    parser.add_argument("--action", default="read", help="action the appeal is about")
    parser.add_argument("--opa", default="opa", help="opa binary for validation")
    parser.add_argument("--policy-dir", help="application policy folder for `opa test`")
    args = parser.parse_args()

    model = RiskModel.load(args.model_dir)
    graph = GraphData.load(args.model_dir)
    index = SimilarityIndex(model)
    cases = index.find(args.user, args.object, args.k, graph.has_access, args.max_per_user or None)

    print(f"pairs most similar to {args.user} -> {args.object} (without access yet)\n")
    print(f"{'user':24}{'object':24}{'similarity':>11}{'user':>8}{'object':>8}{'risk':>8}")
    for c in cases:
        risk = model.risk(c.user, c.object).risk
        print(
            f"{c.user:24}{c.object:24}{c.similarity:>11.4f}"
            f"{c.user_similarity:>8.3f}{c.object_similarity:>8.3f}{risk:>8.3f}"
        )

    found = candidates(
        graph.structure,
        graph.access,
        (args.user, args.object),
        index.user_ids,
        index.object_ids,
        neighbours=[(c.user, c.object) for c in cases],
        object_values=args.object_values,
        object_identity=args.object_identity,
    )
    print(f"\ncandidate patterns, narrowest first ({len(found)} in total; the admin picks one)\n")
    print(f"{'#':>3}{'users':>7}{'pairs':>11}{'kNN':>6}  pattern")
    for i, c in enumerate(found[: args.candidates], start=1):
        users = "?" if c.users is None else str(c.users)
        pairs = f"~{c.pairs}" if c.estimated else str(c.pairs)
        print(f"{i:>3}{users:>7}{pairs:>11}{c.support:>6.0%}  {c.text()}")
    if not found:
        print("    none: the appeal can only be granted as an exact exception")

    if args.pick:
        show_pick(args, model, graph, index, found[args.pick - 1])


def show_pick(args, model, graph, index, chosen) -> None:
    appeal = (args.user, args.object)
    opened = opened_pairs(
        graph.structure, graph.access, appeal, index.user_ids, index.object_ids, chosen.predicates
    )
    scope = assess(opened, model)
    mean_risk = "-" if scope.mean_risk is None else f"{scope.mean_risk:.2f}"
    print(f"\npick #{args.pick}: {chosen.text()}")
    print(f"tier {scope.tier}: {scope.users} users, {scope.pairs} pairs, mean risk {mean_risk}")
    for reason in scope.reasons:
        print(f"  needs acknowledgement: {reason}")

    exception = render_exception("appeal-preview", args.user, args.action, args.object)
    rule = render_rule(
        "appeal-preview",
        args.action,
        chosen.predicates,
        {"users": scope.users, "pairs": scope.pairs, "tier": scope.tier},
    )
    print(f"\n--- appeal-preview-exception.rego\n{exception}\n--- appeal-preview-rule.rego\n{rule}")

    expected = expected_decisions(
        graph.structure, chosen.predicates, opened, index.user_ids, index.object_ids, appeal
    )
    report = validate(
        rule, "app.generated", args.action, graph.structure, expected, args.opa, args.policy_dir
    )
    print("validation")
    for check in report.checks:
        print(f"  {'ok  ' if check.ok else 'FAIL'} {check.name:12} {check.detail}")


if __name__ == "__main__":
    main()
