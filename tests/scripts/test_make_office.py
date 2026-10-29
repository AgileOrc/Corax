import json

import appeal_scenarios
import make_office as office
import pytest
from risk import RiskResult

SEEDS = range(40)


@pytest.fixture(scope="module", params=[0, 7, 23])
def written(request, tmp_path_factory):
    out = tmp_path_factory.mktemp(f"office{request.param}")
    office.write(out, *office.build(request.param))
    return out


def facts(edges):
    found = {}
    for src, relation, dst in edges:
        found.setdefault(src, {}).setdefault(relation, set()).add(dst)
    return found


def by_id(cases):
    return {c["id"]: c for c in cases["cases"]}


@pytest.mark.parametrize("seed", range(200))
def test_every_seed_gives_every_case(seed):
    _, _, scenarios, cases = office.build(seed)

    assert list(by_id(cases)) == ["1", "2", "3", "4", "5a", "5b", "5c", "5d", "5e", "6"]
    assert len(scenarios) == 6


def test_seeds_give_different_offices_and_a_seed_the_same_one():
    assert office.build(3) == office.build(3)
    assert office.build(3)[1] != office.build(4)[1]


@pytest.mark.parametrize("seed", SEEDS)
def test_cases_hold_in_the_graph(seed):
    nodes, edges, _, cases = office.build(seed)
    g, c = facts(edges), by_id(cases)
    readable = lambda u, d: d in g.get(u, {}).get("accessed", set())  # noqa: E731
    role = lambda u: next(iter(g[u]["holds"]))  # noqa: E731

    # 1: denied by the current policy and by every hidden one (no role)
    assert not readable(c["1"]["user"], c["1"]["document"])
    assert role(c["1"]["user"]) in ("role_engineer", "role_analyst")

    # 2, 3: usual candidates come from the access history, unusual ones from outside it
    assert all(readable(u, d) for u, d in c["2"]["pool"])
    assert not any(readable(u, d) for u, d in c["3"]["pool"])

    for case in ("4", "5a", "5b", "5c", "5d", "5e"):
        appeal = c[case]
        assert not readable(appeal["user"], appeal["document"])
        if appeal["expected"] is None:
            assert role(appeal["user"]) in ("role_engineer", "role_analyst")
            continue
        witness = appeal["witness"]
        assert witness["user"] != appeal["user"] and not readable(witness["user"], witness["document"])
        for user, document in ((appeal["user"], appeal["document"]), (witness["user"], witness["document"])):
            assert all(holds(g, p, user, document) for p in appeal["expected"])

    assert c["5a"]["witness"]["after"] == 200 and c["5b"]["witness"]["after"] == 403
    assert c["5c"]["witness"]["after"] == 200 and c["5d"]["witness"]["after"] == 403
    # the regional manager asks for a document of another department in their region
    regional = c["5e"]
    assert role(regional["user"]) == "role_manager" and c["5e"]["witness"]["after"] == 200
    assert not g[regional["user"]]["works_in"] & g[regional["document"]]["owned_by"]
    assert g[regional["user"]]["based_in"] & g[regional["document"]]["stored_in"]
    assert c["6"]["expect"]["witness"]["user"] == c["5a"]["witness"]["user"]


def holds(g, predicate, user, document):
    kind, relation, other = predicate["kind"], predicate["relation"], predicate["other"]
    if kind == "shared":
        return bool(g[user].get(relation, set()) & g[document].get(other, set()))
    return other in g[user].get(relation, set())


def test_scenarios_load_with_the_hidden_pairs(written):
    loaded = appeal_scenarios.load(written / "scenarios.json")
    cases = by_id(json.loads((written / "cases.json").read_text(encoding="utf-8")))

    assert [s.name for s in loaded.scenarios] == ["4_one_off", "5a_manager", "5b_coordinator",
                                                  "5c_security_officer", "5d_facility_manager", "5e_regional_manager"]  # fmt: skip
    for s in loaded.scenarios:
        case = cases[s.name.split("_")[0]]
        assert s.appeal == (case["user"], case["document"])
        if case["expected"]:
            assert s.appeal in s.hidden
            assert (case["witness"]["user"], case["witness"]["document"]) in s.hidden
        else:
            assert s.expected is None and not s.hidden


class Model:
    """A stand-in for the trained model: low risk for the access history and for documents of the
    employee's own department, high elsewhere."""

    def __init__(self, structure, access, nodes, outside=0.95):
        self.structure, self.access, self.outside = structure, access, outside
        self.users = {n: None for n, t in nodes if t == "employee"}
        self.objects = {n: None for n, t in nodes if t == "document"}
        self.threshold = 0.9
        self.metadata = {"risk_threshold": {"value": 0.9, "target_pass_rate": 0.95}}

    def risk(self, user, obj):
        if obj in self.access.get(user, ()):
            risk = 0.1
        elif set(self.structure[user]["works_in"]) & set(self.structure[obj]["owned_by"]):
            risk = 0.2
        else:
            risk = self.outside
        return RiskResult(risk=risk, high_risk=risk > self.threshold)


def nodes_of(folder):
    lines = (folder / "nodes.csv").read_text(encoding="utf-8").splitlines()[1:]
    return [tuple(line.split(",")) for line in lines]


def test_label_picks_the_summaries_and_checks_the_tiers(written):
    cases = json.loads((written / "cases.json").read_text(encoding="utf-8"))
    structure, access = office.read_graph(written)

    problems = office.label(cases, structure, access, Model(structure, access, nodes_of(written)))

    assert problems == [] and cases["verified"] and cases["threshold"] == 0.9
    c = by_id(cases)
    assert c["2"]["risk"] <= 0.9 < c["3"]["risk"]
    assert c["2"]["request"] == f"GET /documents/{c['2']['document']}/summary"
    assert c["5a"]["scope"]["tier"] == c["5b"]["scope"]["tier"] == "small"
    assert c["5c"]["scope"]["tier"] == c["5d"]["scope"]["tier"] == c["5e"]["scope"]["tier"] == "large"
    # a rule is policy: the AI still judges the colleague it opens
    assert c["5a"]["witness"]["after"] == 200
    witness = c["5c"]["witness"]
    assert witness["after"] == (200 if witness["risk"] <= 0.9 else 403)
    assert "risk" not in c["5b"]["witness"] and c["5d"]["witness"]["after"] == 403
    revoked = c["6"]["expect"]["witness"]
    assert (revoked["user"], revoked["document"]) == (c["5a"]["witness"]["user"], c["5a"]["witness"]["document"])


def test_label_denies_a_colleague_the_ai_finds_unusual(written):
    cases = json.loads((written / "cases.json").read_text(encoding="utf-8"))
    structure, access = office.read_graph(written)
    model = Model(structure, access, nodes_of(written))
    model.risk = lambda u, o: RiskResult(risk=0.1 if o in access.get(u, ()) else 0.95, high_risk=False)

    problems = office.label(cases, structure, access, model)

    c = by_id(cases)
    assert c["5a"]["witness"]["after"] == c["5c"]["witness"]["after"] == 403
    assert "the AI denies it" in c["5c"]["witness"]["why"]
    assert any(p.startswith("case 5a: the AI denies the colleague") for p in problems)


def test_label_reports_a_rule_whose_mean_risk_makes_it_large(written):
    cases = json.loads((written / "cases.json").read_text(encoding="utf-8"))
    structure, access = office.read_graph(written)
    model = Model(structure, access, nodes_of(written))
    model.risk = lambda u, o: RiskResult(risk=0.1 if o in access.get(u, ()) else 0.6, high_risk=False)

    problems = office.label(cases, structure, access, model)

    assert not cases["verified"]
    assert any(p.startswith("case 5a: the rule is large") for p in problems)
    assert any(p.startswith("case 3: no candidate") for p in problems)
