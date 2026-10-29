import random
from collections import Counter

import demo_office_cases as cases
import make_office as office
import pytest
from patterns import Predicate
from test_make_office import Model, nodes_of


@pytest.fixture(scope="module")
def stub(tmp_path_factory):
    """An Office of seed 7 with the stand-in model of test_make_office (low risk inside the
    employee's department, high outside)."""
    out = tmp_path_factory.mktemp("office")
    office.write(out, *office.build(7))
    o = object.__new__(cases.Office)
    o.structure, o.access = office.read_graph(out)
    o.model = Model(o.structure, o.access, nodes_of(out))
    o.users, o.objects = list(o.model.users), list(o.model.objects)
    o.hidden = {n: [Predicate(**p) for p in office.HIDDEN[n][1]] for n in cases.SMALL + cases.LARGE}
    o.opened = {n: [(u, d) for u in o.users for d in o.objects if not o.reads(u, d) and cases.holds(o.structure, p, u, d)]
                for n, p in o.hidden.items()}  # fmt: skip
    return o


def test_draws_every_path_and_no_case_twice(stub):
    plans = cases.draw(stub, 120, random.Random(1))

    assert len(plans) == 120 and set(Counter(p["kind"] for p in plans)) == set(cases.KINDS)
    keys = [(p["kind"], p["user"], p["document"], p.get("route")) for p in plans]
    assert len(set(keys)) == len(keys)
    assert cases.draw(stub, 120, random.Random(1)) == plans


def test_plans_hold_in_the_office(stub):
    for p in cases.draw(stub, 120, random.Random(2)):
        user, document, kind = p["user"], p["document"], p["kind"]
        if kind == "policy_denied":
            assert not stub.reads(user, document) and stub.app_policy(user, document, False) is None
        elif kind in ("ai_allowed", "ai_denied"):
            assert stub.app_policy(user, document, p["route"] == "summary")
            assert stub.model.risk(user, document).high_risk == (kind == "ai_denied")
        else:
            assert not stub.reads(user, document)
            if p["pattern"]:
                assert cases.holds(stub.structure, stub.hidden[p["pattern"]], user, document)
            if kind.endswith("_accepted") or kind in ("appeal_large_declined", "revoke"):
                assert p["colleague_user"] != user
                assert cases.holds(stub.structure, stub.hidden[p["pattern"]], p["colleague_user"], p["colleague_document"])


def test_the_tier_names_each_variable_against_its_limit():
    tier = cases._tier({"users": 2, "user_share": 0.02, "pairs": 116, "mean_risk": 0.98, "tier": "large",
                        "reasons": ["116 pairs > 50", "mean risk 0.98 > 0.5"]}, "p")  # fmt: skip

    assert tier["users"]["within"] and not tier["pairs"]["within"] and not tier["mean_risk"]["within"]
    assert tier["tier"] == "large" and tier["why"] == "116 pairs > 50; mean risk 0.98 > 0.5"


def test_a_team_rule_is_a_subset_of_the_department_rule(stub):
    user, document = next((u, d) for u, d in stub.opened["manager"])
    team, department = stub.structure[user]["member_of"][0], stub.structure[user]["works_in"][0]
    shared = {"kind": "shared", "relation": "works_in", "other": "owned_by"}
    found = [{"index": 1, "pattern": "team", "predicates": [shared, {"kind": "user_has", "relation": "member_of", "other": team}]},
             {"index": 2, "pattern": "department", "predicates": [shared, {"kind": "user_has", "relation": "works_in", "other": department}]}]  # fmt: skip

    rows = cases.compare(stub, (user, document), found, 2)

    assert rows[0]["subset_of"] == [2] and rows[1]["contains"] == [1] and rows[1]["chosen"]
    assert rows[0]["pairs"] < rows[1]["pairs"] and rows[0]["users"] <= rows[1]["users"]


def test_the_terminal_shows_traffic_without_case_numbers():
    step = {"step": "the request", "request": {"method": "GET", "path": "/documents/d1", "as": "u1"},
            "policy": "no rule of app.authz or app.generated allows it", "ai": "not asked",
            "response": {"status": 403, "body": {}}, "reason": "denied by policy", "as_expected": True}  # fmt: skip
    lines = cases.text({"id": 7, "title": "u1 opens d1", "user": "u1 (analyst)", "document": "d1 (public)", "steps": [step]})

    shown = [lines[0].split("] ", 1)[1], *lines[1:]]  # without the clock of the first line
    assert not any("case" in line or "7" in line for line in shown)
    assert lines[1] == "   GET /documents/d1 as u1 -> 403 (denied by policy)"


def test_once_a_kind_runs_out_the_others_fill_the_count(stub):
    plans = cases.draw(stub, 400, random.Random(4))

    counts = Counter(p["kind"] for p in plans)
    assert len(plans) == 400 and set(counts) == set(cases.KINDS)
    assert len({(p["kind"], p["user"], p["document"], p.get("route")) for p in plans}) == 400
