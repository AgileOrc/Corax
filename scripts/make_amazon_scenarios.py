"""Turn the Amazon graph into an appeal evaluation dataset by hiding role-based rules.

A (title, resource) pair where almost every user with that title has the resource, and the
resource is mostly used by that title, looks like a role-based rule ("title T gets resource R").
For each chosen rule all its access edges are removed, as if the rule did not exist yet. One user
of the title then appeals for R, and the evaluation checks whether the similar cases and the
candidate patterns lead back to "user works_as T AND object is R".

Rules are picked deterministically, largest first, with no title or resource used twice, so one
training run covers every scenario. A few one-off appeals (a random user and a resource nobody
with their title uses) check that nothing is generalised from them.

These rules are inferred from the data, not taken from Amazon's real policy.

Example:
    python scripts/make_amazon_scenarios.py datasets/amazon-graph datasets/amazon-appeals
    python hgnn-job/run.py --data datasets/amazon-appeals \
        --target-relation has_potential_access --out output/amazon-appeals
    python scripts/evaluate_appeals.py --model-dir output/amazon-appeals \
        --scenarios datasets/amazon-appeals/scenarios.json
"""

import argparse
import csv
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import appeal_scenarios

TARGET, TITLE = "has_potential_access", "works_as"


def select_rules(
    title_of: dict[str, str],
    access: dict[str, set[str]],
    rules: int = 10,
    min_users: int = 15,
    min_coverage: float = 0.9,
) -> list[tuple[str, str, list[str]]]:
    """(title, resource, users of the title with access), largest first, titles and resources unique."""
    members = defaultdict(list)
    for user, title in title_of.items():
        members[title].append(user)
    holders = Counter(r for owned in access.values() for r in owned)

    found = []
    for title, users in members.items():
        if len(users) < min_users:
            continue
        count = Counter(r for u in users for r in access.get(u, ()))
        for resource, inside in count.items():
            outside = holders[resource] - inside
            if inside / len(users) >= min_coverage and outside <= inside:
                with_access = sorted(u for u in users if resource in access.get(u, ()))
                found.append((title, resource, with_access))
    found.sort(key=lambda r: (-len(r[2]), r[0], r[1]))

    chosen, used = [], set()
    for title, resource, with_access in found:
        if title in used or resource in used:
            continue
        chosen.append((title, resource, with_access))
        used.update((title, resource))
        if len(chosen) == rules:
            break
    return chosen


def pick_one_offs(title_of, access, resources, exclude, count, seed):
    """Random (user, resource) pairs where nobody with the user's title has the resource.

    May return fewer than `count` pairs when such pairs are rare.
    """
    rng = random.Random(seed)
    used_by_title = defaultdict(set)
    for user, title in title_of.items():
        used_by_title[title].update(access.get(user, ()))
    users = sorted(u for u in title_of if title_of[u] not in exclude) or sorted(title_of)
    candidates = sorted(r for r in resources if r not in exclude)
    picked = []
    for _ in range(count * 1000):
        if len(picked) == count or not candidates:
            break
        user, resource = rng.choice(users), rng.choice(candidates)
        if resource not in used_by_title[title_of[user]] and (user, resource) not in picked:
            picked.append((user, resource))
    return picked


def main() -> None:
    parser = argparse.ArgumentParser(description="Hide role-based rules in the Amazon graph.")
    parser.add_argument("source", type=Path, help="folder with the Amazon nodes.csv and edges.csv")
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--rules", type=int, default=10)
    parser.add_argument("--one-offs", type=int, default=2)
    parser.add_argument("--min-users", type=int, default=15, help="users with the title")
    parser.add_argument(
        "--min-coverage", type=float, default=0.9, help="share that has the resource"
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    with (args.source / "edges.csv").open(newline="", encoding="utf-8") as f:
        edges = list(csv.DictReader(f))
    title_of = {e["src"]: e["dst"] for e in edges if e["relation"] == TITLE}
    access = defaultdict(set)
    for e in edges:
        if e["relation"] == TARGET:
            access[e["src"]].add(e["dst"])

    chosen = select_rules(title_of, access, args.rules, args.min_users, args.min_coverage)
    hidden = {(u, r) for _, r, users in chosen for u in users}
    resources = {e["dst"] for e in edges if e["relation"] == TARGET}
    exclude = {t for t, _, _ in chosen} | {r for _, r, _ in chosen}
    one_offs = pick_one_offs(title_of, access, resources, exclude, args.one_offs, args.seed)

    scenarios = [
        {
            "name": f"rule_{i:02d}_{title}_{resource}",
            "appeal": (users[0], resource),
            "expected": [
                {"kind": "object_is", "relation": "", "other": resource},
                {"kind": "user_has", "relation": TITLE, "other": title},
            ],
            "hidden_pairs": [(u, resource) for u in users],
        }
        for i, (title, resource, users) in enumerate(chosen, start=1)
    ] + [
        {"name": f"one_off_{i:02d}", "appeal": pair, "expected": None, "hidden_pairs": []}
        for i, pair in enumerate(one_offs, start=1)
    ]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.source / "nodes.csv", args.out_dir / "nodes.csv")
    with (args.out_dir / "edges.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["src", "relation", "dst"])
        for e in edges:
            if not (e["relation"] == TARGET and (e["src"], e["dst"]) in hidden):
                writer.writerow([e["src"], e["relation"], e["dst"]])
    appeal_scenarios.write(args.out_dir, TARGET, True, scenarios)

    print(f"hid {len(chosen)} rules ({len(hidden)} access edges), {len(one_offs)} one-off appeals")
    for title, resource, users in chosen:
        print(f"  {title:14} -> {resource:28} {len(users):4} users")
    print(f"written to {args.out_dir}")


if __name__ == "__main__":
    main()
