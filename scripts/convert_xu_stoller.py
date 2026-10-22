# Source: https://www3.cs.stonybrook.edu/~stoller/software/
# Command: python scripts/convert_xu_stoller.py datasets/xu-stoller/ABACMining/gen-case-studies/university/university-sets_10_1.abac output/xu-stoller/u10-1 --hide-rule 7

import argparse
import csv
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

import appeal_scenarios

TARGET = "accessed"
BOOLEAN = {"true", "false"}
CONDITION = re.compile(r"^(\w+)\s*(in|\[|\])\s*(.+)$")
CONSTRAINT = re.compile(r"^(\w+)\s*(\]|\[|>|=)\s*(\w+)$")


@dataclass
class Rule:
    index: int
    text: str
    subject: list = field(default_factory=list)
    resource: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    constraints: list = field(default_factory=list)


@dataclass
class Policy:
    users: dict
    resources: dict
    rules: list


def _value(text: str):
    text = text.strip()
    if text.startswith("{"):
        return sorted(_normal(v) for v in text.strip("{} ").split())
    return _normal(text)


def _normal(value: str) -> str:
    return value.lower() if value.lower() in BOOLEAN else value


def _attributes_line(body: str) -> tuple[str, dict]:
    tokens, depth, current = [], 0, ""
    for char in body:
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        if char == "," and depth == 0:
            tokens.append(current)
            current = ""
        else:
            current += char
    tokens.append(current)
    ident, attrs = tokens[0].strip(), {}
    for token in tokens[1:]:
        if "=" in token:
            name, value = token.split("=", 1)
            attrs[name.strip()] = _value(value)
    return ident, attrs


def _conditions(text: str) -> list:
    found = []
    for part in filter(None, (p.strip() for p in text.split(","))):
        match = CONDITION.match(part)
        if not match:
            raise ValueError(f"cannot read condition {part!r}")
        attr, op, values = match.groups()
        found.append((attr, op, _value(values) if values.strip().startswith("{") else [_normal(values.strip())]))
    return found


def parse(text: str) -> Policy:
    users, resources, rules = {}, {}, []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, _, rest = line.partition("(")
        body = rest.rsplit(")", 1)[0]
        if name == "userAttrib":
            uid, attrs = _attributes_line(body)
            users[uid] = attrs
        elif name == "resourceAttrib":
            rid, attrs = _attributes_line(body)
            resources[rid] = attrs
        elif name == "rule":
            parts = [p.strip() for p in body.split(";")] + ["", "", "", ""]
            constraints = []
            for part in filter(None, (p.strip() for p in parts[3].split(","))):
                match = CONSTRAINT.match(part)
                if not match:
                    raise ValueError(f"cannot read constraint {part!r}")
                constraints.append(match.groups())
            rules.append(
                Rule(
                    index=len(rules) + 1,
                    text=line,
                    subject=_conditions(parts[0]),
                    resource=_conditions(parts[1]),
                    actions=_value(parts[2]) if parts[2] else [],
                    constraints=constraints,
                )
            )
    return Policy(users, resources, rules)


def _as_set(value) -> set:
    if value is None:
        return set()
    return set(value) if isinstance(value, list) else {value}


def _condition_holds(attrs: dict, attr: str, op: str, values: list) -> bool:
    have = _as_set(attrs.get(attr))
    if op in ("in", "["):
        return len(have) == 1 and bool(have & set(values))
    return set(values) <= have


def _constraint_holds(uid: str, user: dict, resource: dict, a: str, op: str, b: str) -> bool:
    left = {uid} if a == "uid" else _as_set(user.get(a))
    right = _as_set(resource.get(b))
    if not left or not right:
        return False
    if op == "=":
        return len(left) == 1 and left == right
    if op == "]":
        return right <= left and len(right) == 1
    if op == "[":
        return len(left) == 1 and left <= right
    return right <= left


def permits(rule: Rule, uid: str, user: dict, resource: dict) -> bool:
    return (
        all(_condition_holds(user, a, op, v) for a, op, v in rule.subject)
        and all(_condition_holds(resource, a, op, v) for a, op, v in rule.resource)
        and all(_constraint_holds(uid, user, resource, a, op, b) for a, op, b in rule.constraints)
    )


def permitted(policy: Policy, rule: Rule) -> set:
    return {
        (uid, rid)
        for uid, user in policy.users.items()
        for rid, resource in policy.resources.items()
        if permits(rule, uid, user, resource)
    }


def user_references(policy: Policy) -> set:
    names = set()
    for attrs in policy.resources.values():
        for name, value in attrs.items():
            if _as_set(value) and _as_set(value) <= policy.users.keys():
                names.add(name)
    return names


def domains(policy: Policy, references: set) -> dict:
    values: dict[str, set] = {}
    for attrs in [*policy.users.values(), *policy.resources.values()]:
        for name, value in attrs.items():
            if name not in references:
                values.setdefault(name, set()).update(_as_set(value) - BOOLEAN)
    parent = {name: name for name in values}

    def root(name):
        while parent[name] != name:
            name = parent[name]
        return name

    names = sorted(values)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if values[a] & values[b]:
                parent[root(a)] = root(b)
    groups: dict[str, list] = {}
    for name in names:
        groups.setdefault(root(name), []).append(name)
    label = {}
    for members in groups.values():
        short = min(members, key=lambda n: (len(n), n))
        label.update(dict.fromkeys(members, short))
    for attrs in [*policy.users.values(), *policy.resources.values()]:
        for name in attrs:
            label.setdefault(name, name)
    return label


def node(domain: str, value: str) -> str:
    return f"{domain}_{value}"


def build(policy: Policy, hidden_rule: int | None = None):
    references = user_references(policy)
    label = domains(policy, references)
    nodes, edges = {}, []

    def add(node_id, node_type):
        nodes.setdefault(node_id, node_type)

    for uid, attrs in policy.users.items():
        add(f"user_{uid}", "user")
        for name, value in attrs.items():
            for v in _as_set(value):
                add(node(label[name], v), f"value_{label[name]}")
                edges.append((f"user_{uid}", name, node(label[name], v)))
    for rid, attrs in policy.resources.items():
        add(f"res_{rid}", "resource")
        for name, value in attrs.items():
            for v in _as_set(value):
                if name in references:
                    edges.append((f"res_{rid}", name, f"user_{v}"))
                    edges.append((f"user_{v}", f"{name}_of", f"res_{rid}"))
                else:
                    add(node(label[name], v), f"value_{label[name]}")
                    edges.append((f"res_{rid}", name, node(label[name], v)))

    granted = {rule.index: permitted(policy, rule) for rule in policy.rules}
    others = set().union(*(pairs for index, pairs in granted.items() if index != hidden_rule))
    hidden = granted.get(hidden_rule, set()) - others if hidden_rule else set()
    edges += [(f"user_{u}", TARGET, f"res_{r}") for u, r in sorted(others)]
    return nodes, edges, granted, hidden, label, references


def predicates(rule: Rule, label: dict, references: set) -> list[dict] | None:
    found = []
    for side, conditions in (("user_has", rule.subject), ("object_has", rule.resource)):
        for attr, _op, values in conditions:
            if len(values) != 1:
                return None
            found.append({"kind": side, "relation": attr, "other": node(label.get(attr, attr), values[0])})
    for a, op, b in rule.constraints:
        if a == "uid" and b in references and op == "=":
            found.append({"kind": "direct", "relation": f"{b}_of", "other": ""})
        elif a != "uid" and b not in references and op in ("=", "]", "[") and label.get(a) == label.get(b):
            found.append({"kind": "shared", "relation": a, "other": b})
        else:
            return None
    return found


def write(out_dir: Path, policy: Policy, hidden_rule: int, seed: int = 0) -> dict:
    nodes, edges, granted, hidden, label, references = build(policy, hidden_rule)
    rule = next(r for r in policy.rules if r.index == hidden_rule)
    expected = predicates(rule, label, references)
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "nodes.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("id", "type"), *sorted(nodes.items())])
    with (out_dir / "edges.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("src", "relation", "dst"), *edges])
    hidden_pairs = sorted((f"user_{u}", f"res_{r}") for u, r in hidden)
    scenarios = []
    if hidden_pairs:
        scenarios.append(
            {
                "name": f"rule_{hidden_rule:02d}",
                "appeal": random.Random(seed).choice(hidden_pairs),
                "expected": expected,
                "hidden_pairs": hidden_pairs,
            }
        )
    appeal_scenarios.write(out_dir, TARGET, False, scenarios, object_values=True, max_size=3)
    return {"rule": rule.text, "hidden": len(hidden_pairs), "expressible": expected is not None,
            "accessed": sum(e[1] == TARGET for e in edges), "nodes": len(nodes)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a Xu & Stoller .abac policy with one rule hidden.")
    parser.add_argument("source", type=Path, help=".abac file")
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--hide-rule", type=int, required=True, help="1-based rule number to hide")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    policy = parse(args.source.read_text(encoding="utf-8"))
    if not 1 <= args.hide_rule <= len(policy.rules):
        parser.error(f"--hide-rule must be between 1 and {len(policy.rules)}")
    summary = write(args.out_dir, policy, args.hide_rule, args.seed)
    print(f"{len(policy.users)} users, {len(policy.resources)} resources, {len(policy.rules)} rules")
    print(f"hidden rule {args.hide_rule}: {summary['rule']}")
    print(f"{summary['hidden']} pairs only this rule grants; expressible as Corax predicates: {summary['expressible']}")
    print(f"{summary['nodes']} nodes, {summary['accessed']} accessed edges in {args.out_dir}")


if __name__ == "__main__":
    main()
