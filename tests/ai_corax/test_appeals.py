import base64
import json

import numpy as np
import pytest
from appeals import AppealError, Appeals
from config import Settings
from fastapi.testclient import TestClient
from graph import GraphData
from main import create_app
from risk import RiskModel
from tier import TierLimits

HEAD = "position_head"
STRUCTURE = {
    "budi": {"holds": [HEAD], "member_of": ["IF"], "teaches": ["IF201"]},
    "andi": {"holds": ["position_lecturer"], "member_of": ["IF"], "teaches": ["IF202"]},
    "sari": {"holds": [HEAD], "member_of": ["SI"], "teaches": ["SI101"]},
    "tono": {"holds": ["position_lecturer"], "member_of": ["SI"]},
    "ani": {"member_of": ["IF"], "enrolled_in": ["IF201"]},
    "candra": {"member_of": ["IF"], "enrolled_in": ["IF201", "IF202"]},
    "fajar": {"member_of": ["IF"], "enrolled_in": ["IF202"]},
    "dewi": {"member_of": ["SI"], "enrolled_in": ["SI101"]},
    "gita": {"member_of": ["SI"], "enrolled_in": ["SI102"]},
}
ACCESS = {"budi": ["ani", "candra"], "andi": ["candra", "fajar"], "sari": ["dewi"]}
# nina is a new lecturer: an embedding, but no relation in the graph
LECTURERS = ["budi", "andi", "sari", "tono", "nina"]
STUDENTS = ["ani", "candra", "fajar", "dewi", "gita"]
HEAD_RULE = [
    {"kind": "shared", "relation": "member_of", "other": "member_of"},
    {"kind": "user_has", "relation": "holds", "other": HEAD},
]


@pytest.fixture
def appeal_model(tmp_path):
    # IF people point one way, SI people the other: same program = low risk
    if_, si = [1.0, 0.0], [0.0, 1.0]
    lecturers = [if_, if_, si, si, [0.5, 0.5]]
    students = [[3 * x for x in v] for v in (if_, if_, if_, si, si)]
    np.savez(
        tmp_path / "embeddings.npz",
        lecturer=np.array(lecturers, dtype=np.float32),
        student=np.array(students, dtype=np.float32),
    )
    files = {
        "node_ids.json": {"lecturer": LECTURERS, "student": STUDENTS},
        "metadata.json": {
            "target_edge_type": ["lecturer", "accessed", "student"],
            "risk_threshold": {"value": 0.9, "target_pass_rate": 0.99},
        },
        "graph.json": STRUCTURE,
        "access.json": ACCESS,
    }
    for name, content in files.items():
        (tmp_path / name).write_text(json.dumps(content), encoding="utf-8")
    return tmp_path


def make_appeals(model_dir, tmp_path, opa, **overrides) -> Appeals:
    settings = Settings(
        model_dir=model_dir,
        opa_path=opa,
        generated_dir=tmp_path / "generated",
        state_dir=tmp_path / "state",
        **overrides,
    )
    return Appeals(settings, RiskModel.load(model_dir), GraphData.load(model_dir))


def number_of(state, predicates) -> int:
    return next(c["number"] for c in state["candidates"] if c["predicates"] == predicates)


def events(appeals) -> list[str]:
    return [json.loads(line)["event"] for line in appeals.audit.read_text().splitlines()]


def test_submit_writes_the_exception_and_lists_candidates(appeal_model, tmp_path, opa):
    appeals = make_appeals(appeal_model, tmp_path, opa)

    state = appeals.submit("appeal-1", "budi", "fajar", "read", "admin_1")

    assert state["status"] == "awaiting_choice"
    exception = (tmp_path / "generated" / "appeal-1-exception.rego").read_text()
    assert "package app.exceptions" in exception
    assert 'input.user.id == "budi"' in exception
    assert number_of(state, HEAD_RULE) >= 1
    # narrowest first, as in scripts/similar_cases.py
    pairs = [c["pairs"] for c in state["candidates"]]
    assert pairs == sorted(pairs)
    assert state["approved_by"] == "admin_1"
    assert events(appeals) == ["approved", "exception_applied", "candidates"]
    assert json.loads((tmp_path / "state" / "appeals" / "appeal-1.json").read_text()) == state


def test_small_tier_rule_is_applied_at_once(appeal_model, tmp_path, opa):
    appeals = make_appeals(appeal_model, tmp_path, opa)
    state = appeals.submit("appeal-1", "budi", "fajar", "read", "admin_1")

    state = appeals.pick("appeal-1", number_of(state, HEAD_RULE), "admin_1")

    assert state["status"] == "applied"
    assert state["picked"]["tier"] == "small"
    # the only new pair: sari, head of SI, reads gita (dewi she already reads)
    assert (state["picked"]["users"], state["picked"]["pairs"]) == (1, 1)
    assert all(check["ok"] for check in state["validation"])
    rule = (tmp_path / "generated" / "appeal-1-rule.rego").read_text()
    assert rule == state["picked"]["rule"]
    assert "package app.generated" in rule
    assert events(appeals)[-2:] == ["picked", "rule_applied"]


def test_large_tier_waits_for_confirmation(appeal_model, tmp_path, opa):
    appeals = make_appeals(appeal_model, tmp_path, opa, tier_limits=TierLimits(max_users=0))
    state = appeals.submit("appeal-1", "budi", "fajar", "read", "admin_1")

    state = appeals.pick("appeal-1", number_of(state, HEAD_RULE), "admin_1")

    assert state["status"] == "awaiting_confirmation"
    assert state["picked"]["reasons"] == ["1 users > 0"]
    assert not (tmp_path / "generated" / "appeal-1-rule.rego").exists()

    state = appeals.confirm("appeal-1", "admin_2")

    assert state["status"] == "applied"
    assert state["confirmed_by"] == "admin_2"
    assert (tmp_path / "generated" / "appeal-1-rule.rego").exists()


def test_rejected_appeal_keeps_only_the_exception(appeal_model, tmp_path, opa):
    appeals = make_appeals(appeal_model, tmp_path, opa, tier_limits=TierLimits(max_users=0))
    state = appeals.submit("appeal-1", "budi", "fajar", "read", "admin_1")
    appeals.pick("appeal-1", number_of(state, HEAD_RULE), "admin_1")

    state = appeals.reject("appeal-1", "admin_1")

    assert state["status"] == "rejected"
    assert sorted(p.name for p in (tmp_path / "generated").iterdir()) == [
        "appeal-1-exception.rego"
    ]
    with pytest.raises(AppealError) as error:
        appeals.confirm("appeal-1", "admin_1")
    assert error.value.status == 409


def test_failed_app_tests_reject_the_rule(appeal_model, tmp_path, opa):
    # an application test that the head-of-program rule breaks: sari must never read gita
    policy = tmp_path / "policy"
    policy.mkdir()
    (policy / "guard_test.rego").write_text(
        "package guard_test\n\n"
        "test_sari_never_reads_gita if {\n"
        '\tnot data.app.generated.allow with input as {"user": {"id": "sari"}, '
        '"action": "read", "resource": {"id": "gita"}}\n'
        f"\t\twith data.corax.graph as {json.dumps(STRUCTURE)}\n"
        "}\n",
        encoding="utf-8",
    )
    appeals = make_appeals(appeal_model, tmp_path, opa, policy_dir=policy)
    state = appeals.submit("appeal-1", "budi", "fajar", "read", "admin_1")

    state = appeals.pick("appeal-1", number_of(state, HEAD_RULE), "admin_1")

    assert state["status"] == "rule_rejected"
    assert [(c["name"], c["ok"]) for c in state["validation"]][-1] == ("app tests", False)
    assert not (tmp_path / "generated" / "appeal-1-rule.rego").exists()


def test_user_without_relations_gets_only_the_exception(appeal_model, tmp_path, opa):
    appeals = make_appeals(appeal_model, tmp_path, opa)

    state = appeals.submit("appeal-1", "nina", "gita", "read", "admin_1")

    assert state["status"] == "exception_only"
    assert state["candidates"] == []
    with pytest.raises(AppealError) as error:
        appeals.pick("appeal-1", 1, "admin_1")
    assert error.value.status == 409


@pytest.mark.parametrize(
    ("call", "status"),
    [
        (lambda a: a.submit("appeal-1", "budi", "fajar", "read", "admin_1"), 409),
        (lambda a: a.submit("appeal-2", "nobody", "fajar", "read", "admin_1"), 404),
        (lambda a: a.submit("appeal-2", "budi", "nothing", "read", "admin_1"), 404),
        (lambda a: a.submit("../evil", "budi", "fajar", "read", "admin_1"), 400),
        (lambda a: a.pick("appeal-1", 999, "admin_1"), 400),
        (lambda a: a.pick("appeal-9", 1, "admin_1"), 404),
        (lambda a: a.confirm("appeal-1", "admin_1"), 409),
    ],
)
def test_invalid_calls_are_refused(appeal_model, tmp_path, opa, call, status):
    appeals = make_appeals(appeal_model, tmp_path, opa)
    appeals.submit("appeal-1", "budi", "fajar", "read", "admin_1")

    with pytest.raises(AppealError) as error:
        call(appeals)
    assert error.value.status == status


# --- HTTP API -------------------------------------------------------------------------


def bearer(sub: str) -> dict:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    # not signed: OPA verifies the token at the gateway, ai-corax only reads "sub"
    return {"Authorization": f"Bearer {part({'alg': 'HS256'})}.{part({'sub': sub})}.x"}


def test_appeal_through_the_api(appeal_model, tmp_path, opa):
    settings = Settings(
        model_dir=appeal_model,
        opa_path=opa,
        generated_dir=tmp_path / "generated",
        state_dir=tmp_path / "state",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["appeals"] is True
        body = {"appeal_id": "appeal-1", "user": "budi", "object": "fajar", "action": "read"}
        state = client.post("/appeals", json=body, headers=bearer("admin_1")).json()
        assert state["approved_by"] == "admin_1"

        number = number_of(state, HEAD_RULE)
        response = client.post("/appeals/appeal-1/pick", json={"candidate": number},
                               headers=bearer("admin_2"))  # fmt: skip
        assert response.status_code == 200
        assert response.json()["status"] == "applied"
        assert response.json()["picked"]["by"] == "admin_2"
        assert client.get("/appeals/appeal-1").json()["status"] == "applied"
        assert client.post("/appeals/appeal-1/reject").status_code == 409
        assert client.get("/appeals/appeal-9").status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"appeal_id": "../x", "user": "budi", "object": "fajar"},
        {"appeal_id": "a", "user": "", "object": "fajar"},
        {"appeal_id": "a", "user": "budi", "object": "fajar", "action": 'read"}'},
    ],
)
def test_invalid_appeal_body_is_rejected(appeal_model, tmp_path, body):
    settings = Settings(model_dir=appeal_model, state_dir=tmp_path / "state",
                        generated_dir=tmp_path / "generated")  # fmt: skip
    with TestClient(create_app(settings)) as client:
        assert client.post("/appeals", json=body).status_code == 422


def test_appeals_are_off_without_graph(model_dir, tmp_path):
    settings = Settings(model_dir=model_dir, state_dir=tmp_path / "state")
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["appeals"] is False
        body = {"appeal_id": "appeal-1", "user": "u1", "object": "r1"}
        assert client.post("/appeals", json=body).status_code == 503
