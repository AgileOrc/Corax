import base64
import hashlib
import hmac
import json

import demo_backend
from tier import TierLimits


def test_envoy_fields():
    line = ("[2026-10-25T14:00:00.000Z] GET /documents/document_D116/summary -> 403 reason=high AI risk "
            "risk=0.9999 trace=demo-1-3")  # fmt: skip
    assert demo_backend.envoy_fields(line) == {"reason": "high AI risk", "risk": "0.9999"}
    denied = "[...] GET /documents/document_D067 -> 403 reason=denied by policy risk=- trace=demo-1-1"
    assert demo_backend.envoy_fields(denied) == {"reason": "denied by policy", "risk": None}


def test_indicators_mark_what_is_over_the_limit():
    lines = demo_backend.indicators({"users": 24, "user_share": 0.3, "pairs": 14, "mean_risk": 0.16}, TierLimits())

    assert lines[0].split() == ["indicators", "value", "limit"]
    assert lines[1].split() == ["share", "of", "users", "30%", "40%", "ok"]
    assert lines[2].split() == ["new", "pairs", "14", "50", "ok"]
    assert lines[3].split() == ["mean", "risk", "0.16", "0.50", "ok"]


def test_rule_body_without_package_and_metadata():
    rego = 'package app.generated\n\n# METADATA\n# title: "appeal-0001"\nallow if {\n\tinput.action == "read"\n}\n'

    assert [line.strip() for line in demo_backend.rule_body(rego)] == ["allow if {", 'input.action == "read"', "}"]


def candidate(index, users, *predicates):
    return {"index": index, "users": users,
            "predicates": [{"kind": k, "relation": r, "other": o} for k, r, o in predicates]}  # fmt: skip


def test_pick_exact_or_department_wide():
    role = candidate(1, 4, demo_backend.BROAD, ("user_has", "holds", "role_coordinator"))
    site = candidate(2, 30, demo_backend.BROAD, ("user_has", "located_in", "site_jakarta"))
    department = candidate(3, 24, demo_backend.BROAD, ("user_has", "works_in", "department_sales"))
    widest = candidate(4, 90, ("user_has", "holds", "role_analyst"))

    assert demo_backend.pick([role, site, department], {demo_backend.BROAD, ("user_has", "holds", "role_coordinator")}) is role
    assert demo_backend.pick([role, site, department, widest], None) is department
    assert demo_backend.pick([role, site, widest], None) is site
    assert demo_backend.pick([candidate(5, 99, demo_backend.BROAD), department], None)["index"] == 5


def test_graph_opens_the_pairs_of_a_pattern(tmp_path):
    (tmp_path / "nodes.csv").write_text("id,type\nana,employee\nbob,employee\nd1,document\nd2,document\n")
    (tmp_path / "edges.csv").write_text(
        "src,relation,dst\nana,works_in,sales\nbob,works_in,finance\nd1,owned_by,sales\nd2,owned_by,finance\n"
        "ana,holds,role_manager\nana,accessed,d1\n"
    )
    graph = demo_backend.Graph(tmp_path)
    same_department = [{"kind": "shared", "relation": "works_in", "other": "owned_by"}]

    assert graph.opened(same_department, skip=set()) == [("bob", "d2")]  # ana reads d1 already
    assert graph.opened(same_department, skip={"bob"}) == []
    manager = same_department + [{"kind": "user_has", "relation": "holds", "other": "role_manager"}]
    assert graph.holds(manager[1], "ana", "d2") and not graph.holds(manager[1], "bob", "d2")


JWT = {"iss": "corax-demo", "aud": "corax", "secret": "demo-secret"}


def decode(token: str) -> tuple[dict, bytes, bytes]:
    head, body, signature = token.split(".")
    pad = lambda part: part + "=" * (-len(part) % 4)  # noqa: E731
    return json.loads(base64.urlsafe_b64decode(pad(body))), f"{head}.{body}".encode(), base64.urlsafe_b64decode(pad(signature))


def test_make_token_signs_with_the_demo_secret_or_a_forged_one():
    claims, signed, signature = decode(demo_backend.make_token("employee_E001", JWT))
    assert claims["sub"] == "employee_E001" and claims["iss"] == "corax-demo" and claims["aud"] == "corax"
    assert signature == hmac.new(b"demo-secret", signed, hashlib.sha256).digest()

    _, signed, forged = decode(demo_backend.make_token("admin_01", JWT, secret="other"))
    assert forged != hmac.new(b"demo-secret", signed, hashlib.sha256).digest()


def test_make_token_can_be_expired():
    claims, _, _ = decode(demo_backend.make_token("employee_E001", JWT, lifetime=-60))
    assert claims["exp"] < demo_backend.time.time()


def test_summary_counts_and_names_the_cases_that_failed():
    lines = demo_backend.summary([(1, "BOLA", "403", True), (2, "small rule", "large", False)])

    assert lines[0] == "Summary: 2 cases, 1 as expected, 1 not: 2"
    assert lines[1].split()[:2] == ["1", "ok"] and lines[2].split()[:2] == ["2", "FAIL"]


