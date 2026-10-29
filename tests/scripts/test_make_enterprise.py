import json
import sys
from collections import defaultdict

import appeal_scenarios
import make_enterprise as enterprise
import pytest
from patterns import Predicate

ARGS = dict(teams=3, team_size=12, projects=4, documents=8, seed=0)


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


def test_documents_and_employees_have_two_projects_of_their_department(built):
    nodes, g, _, _, _ = built
    owner = {p: g[p]["owned_by"] for p in of_type(nodes, "project")}
    for document in of_type(nodes, "document"):
        assert len(set(g[document]["belongs_to"])) == 2
        assert all(owner[p] == g[document]["owned_by"] for p in g[document]["belongs_to"])
    for employee in of_type(nodes, "employee"):
        own = [p for p in g[employee]["works_on"] if owner[p] == g[employee]["works_in"]]
        assert len(own) == 2


@pytest.mark.parametrize("role", list(enterprise.DEPARTMENT_ROLES.values()))
def test_department_roles_have_one_holder_per_department(built, role):
    nodes, g, _, _, _ = built
    holders = [e for e in of_type(nodes, "employee") if g[e]["holds"] == [f"role_{role}"]]
    assert sorted(g[e]["works_in"][0] for e in holders) == sorted(of_type(nodes, "department"))


def test_only_auditors_are_cleared_and_only_hr_partners_support(built):
    nodes, g, _, _, _ = built
    employees = of_type(nodes, "employee")
    cleared = {e for e in employees if g[e]["cleared_for"]}
    supporting = {e for e in employees if g[e]["supports"]}

    assert cleared == {e for e in employees if g[e]["holds"] == ["role_auditor"]} and len(cleared) == 2
    assert supporting == {e for e in employees if g[e]["holds"] == ["role_hr_partner"]}
    assert sorted(g[e]["supports"][0] for e in supporting) == sorted(
        d for d in of_type(nodes, "department") if d != "department_hr"
    )


@pytest.mark.parametrize("name", list(enterprise.HIDDEN))
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
    nodes, g, accessed, scenarios, demo = built
    ids = {n for n, _ in nodes}

    assert all({r["user"], r["document"]} <= ids for r in demo["reads"])
    assert all(r["expect"] == (200 if (r["user"], r["document"]) in accessed else 403) for r in demo["reads"])
    for appeal in demo["appeals"]:
        assert (appeal["user"], appeal["document"]) == scenarios[appeal["scenario"]]["appeal"]
    apac = next(r for r in demo["reads"] if "(APAC)" in r["name"])
    assert g[apac["user"]]["based_in"] == ["region_apac"]
    assert {r["user"] for r in demo["summaries"]} <= set(of_type(nodes, "employee"))


def test_witnesses_are_hidden_pairs_of_someone_else(built):
    _, _, _, scenarios, demo = built
    for appeal in demo["appeals"]:
        if appeal["witness"]:
            assert tuple(appeal["witness"]) in scenarios[appeal["scenario"]]["hidden_pairs"]
            assert appeal["witness"][0] != appeal["user"]
    assert {a["admin"] for a in demo["appeals"]} == {"accept", "decline"}


def test_appeals_outside_the_appellants_region_drop_its_predicates(built):
    _, g, _, scenarios, _ = built
    for name in ("auditor", "hr_partner"):
        user, document = scenarios[name]["appeal"]
        assert g[user]["based_in"] != g[document]["stored_in"]


def test_main_writes_graph_scenarios_and_demo(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["make_enterprise.py", str(tmp_path), "--seed", "5"])
    enterprise.main()

    assert {p.name for p in tmp_path.iterdir()} == {
        "nodes.csv", "edges.csv", "scenarios.json", "hidden", "demo.json",
    }  # fmt: skip
    loaded = appeal_scenarios.load(tmp_path / "scenarios.json")
    assert [s.name for s in loaded.scenarios] == [
        "manager", "coordinator", "data_steward", "quality_lead", "security_officer", "facility_manager",
        "auditor", "hr_partner", "one_off", "one_off_hr",
    ]  # fmt: skip
    assert json.loads((tmp_path / "demo.json").read_text())["admin"] == enterprise.ADMIN


def test_main_needs_three_teams_of_five(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["make_enterprise.py", str(tmp_path), "--teams", "2"])
    with pytest.raises(SystemExit):
        enterprise.main()
