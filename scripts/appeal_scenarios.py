"""Appeal scenarios: an appealed pair plus the answer an evaluation compares against.

scenarios.json, next to nodes.csv and edges.csv:

    {
      "target_relation": "accessed",
      "object_identity": false,          # allow "object is <id>" predicates (Amazon: true)
      "scenarios": [
        {
          "name": "head_of_program",
          "appeal": ["lecturer_head_P0", "student_P0_05"],
          "expected": [{"kind": "user_has", "relation": "holds", "other": "position_head_of_program"},
                       {"kind": "shared", "relation": "member_of", "other": "member_of"}],
          "hidden": "hidden/head_of_program.csv"     # pairs the expected rule should open
        },
        {"name": "one_off", "appeal": [...], "expected": null, "hidden": null}
      ]
    }

A scenario with "expected": null is a one-off: no rule should be generalised from it.
"""

import csv
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Scenario:
    name: str
    appeal: tuple[str, str]
    expected: tuple[dict, ...] | None  # predicates as {"kind", "relation", "other"}
    hidden: frozenset[tuple[str, str]]  # empty for a one-off


@dataclass(frozen=True)
class ScenarioSet:
    target_relation: str
    object_identity: bool
    scenarios: tuple[Scenario, ...]


def write(out_dir: Path, target_relation: str, object_identity: bool, scenarios: list[dict]):
    """Write scenarios.json and one hidden/<name>.csv per scenario with hidden pairs.

    Each scenario dict has name, appeal, expected (list of predicate dicts or None) and
    hidden_pairs (list of (user, object), empty for a one-off).
    """
    (out_dir / "hidden").mkdir(parents=True, exist_ok=True)
    entries = []
    for s in scenarios:
        hidden = None
        if s["hidden_pairs"]:
            hidden = f"hidden/{s['name']}.csv"
            with (out_dir / hidden).open("w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerows([("user", "object"), *sorted(s["hidden_pairs"])])
        entries.append(
            {
                "name": s["name"],
                "appeal": list(s["appeal"]),
                "expected": s["expected"],
                "hidden": hidden,
            }
        )
    document = {
        "target_relation": target_relation,
        "object_identity": object_identity,
        "scenarios": entries,
    }
    (out_dir / "scenarios.json").write_text(json.dumps(document, indent=2), encoding="utf-8")


def load(path: Path) -> ScenarioSet:
    document = json.loads(path.read_text(encoding="utf-8"))
    scenarios = []
    for entry in document["scenarios"]:
        hidden = frozenset()
        if entry.get("hidden"):
            with (path.parent / entry["hidden"]).open(newline="", encoding="utf-8") as f:
                hidden = frozenset((row["user"], row["object"]) for row in csv.DictReader(f))
        expected = entry.get("expected")
        scenarios.append(
            Scenario(
                name=entry["name"],
                appeal=tuple(entry["appeal"]),
                expected=None if expected is None else tuple(expected),
                hidden=hidden,
            )
        )
    return ScenarioSet(
        target_relation=document["target_relation"],
        object_identity=document.get("object_identity", False),
        scenarios=tuple(scenarios),
    )
