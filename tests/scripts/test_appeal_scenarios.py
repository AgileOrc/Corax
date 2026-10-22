import json

import appeal_scenarios
import make_amazon_scenarios as amazon
import make_dummy as campus


def test_write_and_load_round_trip(tmp_path):
    expected = [{"kind": "user_has", "relation": "holds", "other": "head"}]
    appeal_scenarios.write(
        tmp_path,
        "accessed",
        False,
        [
            {
                "name": "rule",
                "appeal": ("u1", "o1"),
                "expected": expected,
                "hidden_pairs": [("u2", "o2"), ("u1", "o1")],
            },
            {"name": "single", "appeal": ("u3", "o3"), "expected": None, "hidden_pairs": []},
        ],
    )

    loaded = appeal_scenarios.load(tmp_path / "scenarios.json")

    assert loaded.target_relation == "accessed"
    assert loaded.object_identity is False
    rule, single = loaded.scenarios
    assert rule.appeal == ("u1", "o1")
    assert rule.expected == tuple(expected)
    assert rule.hidden == {("u1", "o1"), ("u2", "o2")}
    assert single.expected is None
    assert single.hidden == frozenset()
    assert not (tmp_path / "hidden" / "single.csv").exists()


def test_mini_campus_hidden_rule_is_heads_and_their_own_students_without_access():
    nodes, edges, scenarios = campus.build(programs=3, lecturers=2, students=6, courses=3, seed=1)
    accessed = {(s, d) for s, r, d in edges if r == "accessed"}
    program = {s: d for s, r, d in edges if r == "member_of"}

    head_rule = scenarios[0]
    assert head_rule["name"] == "head_of_program"
    for user, student in head_rule["hidden_pairs"]:
        assert user.startswith("lecturer_head_")
        assert program[user] == program[student]
        assert (user, student) not in accessed
    assert head_rule["appeal"] in head_rule["hidden_pairs"]
    assert head_rule["appeal"][0] == "lecturer_head_P0"


def test_mini_campus_one_off_has_no_access_and_crosses_programs():
    _, edges, scenarios = campus.build(programs=3, lecturers=2, students=6, courses=3, seed=1)
    program = {s: d for s, r, d in edges if r == "member_of"}
    accessed = {(s, d) for s, r, d in edges if r == "accessed"}

    one_off = scenarios[1]
    user, student = one_off["appeal"]
    assert one_off["expected"] is None
    assert program[user] != program[student]
    assert (user, student) not in accessed


def amazon_like():
    title_of = {f"a{i}": "t1" for i in range(4)} | {f"b{i}": "t2" for i in range(4)}
    access = {
        "a0": {"r1", "r3"},
        "a1": {"r1"},
        "a2": {"r1"},
        "a3": {"r1"},
        "b0": {"r2", "r1"},
        "b1": {"r2"},
        "b2": {"r2", "r3"},
        "b3": {"r2"},
    }
    return title_of, access


def test_rules_are_role_resource_pairs_with_high_coverage():
    title_of, access = amazon_like()

    chosen = amazon.select_rules(title_of, access, rules=10, min_users=3, min_coverage=0.9)

    assert chosen == [
        ("t1", "r1", ["a0", "a1", "a2", "a3"]),
        ("t2", "r2", ["b0", "b1", "b2", "b3"]),
    ]


def test_titles_and_resources_are_used_once():
    title_of, access = amazon_like()
    title_of |= {f"c{i}": "t3" for i in range(4)}
    access |= {f"c{i}": {"r1"} for i in range(4)}

    chosen = amazon.select_rules(title_of, access, rules=10, min_users=3, min_coverage=0.9)

    resources = [r for _, r, _ in chosen]
    titles = [t for t, _, _ in chosen]
    assert len(resources) == len(set(resources))
    assert len(titles) == len(set(titles))


def test_small_titles_are_ignored():
    title_of, access = amazon_like()

    assert amazon.select_rules(title_of, access, min_users=5) == []


def test_one_offs_use_resources_unknown_to_the_title():
    title_of, access = amazon_like()
    resources = {"r1", "r2", "r3", "r4"}

    picked = amazon.pick_one_offs(title_of, access, resources, exclude={"r1"}, count=5, seed=0)

    assert len(picked) == 5
    for user, resource in picked:
        same_title = [u for u, t in title_of.items() if t == title_of[user]]
        assert all(resource not in access.get(u, ()) for u in same_title)
        assert resource != "r1"


def test_amazon_command_hides_the_rules(tmp_path):
    import csv
    import subprocess
    import sys
    from pathlib import Path

    source = tmp_path / "source"
    source.mkdir()
    title_of, access = amazon_like()
    title_of["z0"], access["z0"] = "t9", {"r4"}
    nodes = [(u, "user") for u in title_of] + [(t, "title") for t in ("t1", "t2", "t9")]
    nodes += [(r, "resource") for r in ("r1", "r2", "r3", "r4")]
    edges = [(u, "works_as", t) for u, t in title_of.items()]
    edges += [(u, "has_potential_access", r) for u, rs in access.items() for r in sorted(rs)]
    with (source / "nodes.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("id", "type"), *nodes])
    with (source / "edges.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("src", "relation", "dst"), *edges])
    script = Path(__file__).parents[2] / "scripts" / "prepare" / "make_amazon_scenarios.py"

    completed = subprocess.run(
        [sys.executable, str(script), str(source), str(tmp_path / "out"),
         "--min-users", "3", "--one-offs", "1"],
        capture_output=True, text=True, check=False,
    )

    assert completed.returncode == 0, completed.stderr
    with (tmp_path / "out" / "edges.csv").open(newline="", encoding="utf-8") as f:
        kept = {(r["src"], r["dst"]) for r in csv.DictReader(f) if r["relation"] != "works_as"}
    assert kept == {("a0", "r3"), ("b2", "r3"), ("b0", "r1"), ("z0", "r4")}
    document = json.loads((tmp_path / "out" / "scenarios.json").read_text(encoding="utf-8"))
    assert document["object_identity"] is True
    assert [s["expected"] is None for s in document["scenarios"]] == [False, False, True]
