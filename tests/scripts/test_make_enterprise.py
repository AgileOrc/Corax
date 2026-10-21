import json
import sys
from collections import defaultdict

import appeal_scenarios
import make_enterprise as enterprise
import pytest
from patterns import Predicate

ARGS = dict(teams=2, team_size=12, projects=3, documents=8, seed=0)


@pytest.fixture(scope="module")
def built():
    nodes, edges, scenarios, demo = enterprise.build(**ARGS)
    structure = defaultdict(lambda: defaultdict(list))
    for src, relation, dst in edges:
        if relation != "accessed":
            structure[src][relation].append(dst)
    accessed = {(s, d) for s, r, d in edges if r == "accessed"}
    return nodes, structure, accessed, {s["name"]: s for s in scenarios}, demo


def of_type(nodes, node_type):
    return [n for n, t in nodes if t == node_type]


def test_access_history_is_the_current_policy(built):
    nodes, g, accessed, _, _ = built

    def current_policy(e, d):
        same_project = set(g[e]["works_on"]) & set(g[d]["belongs_to"])
        public_of_own_department = "classification_public" in g[d]["classified_as"] and (
            g[e]["works_in"] == g[d]["owned_by"]
        )
        return bool(same_project) or public_of_own_department

    pairs = {(e, d) for e in of_type(nodes, "employee") for d in of_type(nodes, "document")}
    assert accessed == {pair for pair in pairs if current_policy(*pair)}


@pytest.mark.parametrize("name", ["manager", "security_officer"])
def test_hidden_rule_opens_exactly_its_pairs(built, name):
    nodes, g, accessed, scenarios, _ = built
    scenario = scenarios[name]
    predicates = [Predicate(**p) for p in scenario["expected"]]

    opened = {
        (e, d)
        for e in of_type(nodes, "employee")
        for d in of_type(nodes, "document")
        if all(p.holds(g, e, d) for p in predicates) and (e, d) not in accessed
    }
    assert opened == set(scenario["hidden_pairs"])
    assert scenario["appeal"] in opened


def test_appeals_point_at_one_link_only(built):
    _, g, _, scenarios, _ = built
    manager, document = scenarios["manager"]["appeal"]
    assert g[manager]["works_in"] == g[document]["owned_by"]
    assert g[manager]["based_in"] != g[document]["stored_in"]

    officer, document = scenarios["security_officer"]["appeal"]
    assert g[officer]["based_in"] == g[document]["stored_in"] == ["region_emea"]
    assert g[officer]["works_in"] != g[document]["owned_by"]


def test_one_off_is_a_confidential_document_without_access(built):
    _, g, accessed, scenarios, _ = built
    one_off = scenarios["one_off"]
    engineer, document = one_off["appeal"]

    assert one_off["expected"] is None
    assert g[engineer]["holds"] == ["role_engineer"]
    assert g[document]["classified_as"] == ["classification_confidential"]
    assert (engineer, document) not in accessed


def test_demo_uses_graph_nodes_and_scenario_appeals(built):
    nodes, g, _, scenarios, demo = built
    ids = {n for n, _ in nodes}

    assert all({r["user"], r["document"]} <= ids for r in demo["reads"])
    for appeal in demo["appeals"]:
        assert (appeal["user"], appeal["document"]) == scenarios[appeal["scenario"]]["appeal"]
    apac = next(r for r in demo["reads"] if "(APAC)" in r["name"])
    assert g[apac["user"]]["based_in"] == ["region_apac"]


def test_main_writes_graph_scenarios_and_demo(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["make_enterprise.py", str(tmp_path), "--seed", "5"])
    enterprise.main()

    assert {p.name for p in tmp_path.iterdir()} == {
        "nodes.csv", "edges.csv", "scenarios.json", "hidden", "demo.json",
    }  # fmt: skip
    loaded = appeal_scenarios.load(tmp_path / "scenarios.json")
    assert [s.name for s in loaded.scenarios] == ["manager", "security_officer", "one_off"]
    assert json.loads((tmp_path / "demo.json").read_text())["admin"] == enterprise.ADMIN
