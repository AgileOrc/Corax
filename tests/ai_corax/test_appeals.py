import json

import numpy as np
import pytest
from config import Settings
from fastapi.testclient import TestClient
from main import create_app
from tier import TierLimits

STRUCTURE = {
    "budi": {"holds": ["head"], "member_of": ["IF"]},
    "sari": {"holds": ["head"], "member_of": ["SI"]},
    "andi": {"holds": ["lecturer"], "member_of": ["IF"]},
    "ani": {"member_of": ["IF"]},
    "candra": {"member_of": ["IF"]},
    "dewi": {"member_of": ["SI"]},
}
ACCESS = {"budi": ["ani"]}
ADMIN = {"x-corax-user": "admin_rina"}
APPEAL = {"user": "budi", "object": "candra", "action": "read_grades", "reason": "head of program"}
HEAD_RULE = "user.member_of = object.member_of AND user holds head"


@pytest.fixture
def model_dir(tmp_path):
    folder = tmp_path / "model"
    folder.mkdir()
    rng = np.random.default_rng(0)
    np.savez(
        folder / "embeddings.npz",
        lecturer=rng.normal(size=(3, 4)).astype(np.float32),
        student=rng.normal(size=(3, 4)).astype(np.float32),
    )
    node_ids = {"lecturer": ["budi", "sari", "andi"], "student": ["ani", "candra", "dewi"]}
    (folder / "node_ids.json").write_text(json.dumps(node_ids), encoding="utf-8")
    metadata = {"target_edge_type": ["lecturer", "accessed", "student"], "risk_threshold": {"value": 0.99}}
    (folder / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    (folder / "graph.json").write_text(json.dumps(STRUCTURE), encoding="utf-8")
    (folder / "access.json").write_text(json.dumps(ACCESS), encoding="utf-8")
    return folder


@pytest.fixture
def settings(model_dir, tmp_path, opa):
    return Settings(
        model_dir=model_dir,
        opa_path=opa,
        generated_dir=tmp_path / "generated",
        appeals_dir=tmp_path / "appeals",
        tier_limits=TierLimits(max_users=1, max_pairs=1, max_mean_risk=1.0),
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def create(client):
    response = client.post("/corax/appeals", json=APPEAL, headers=ADMIN)
    assert response.status_code == 201, response.json()
    return response.json()


def index_of(record, pattern):
    return next(c["index"] for c in record["candidates"] if c["pattern"] == pattern)


def test_appeal_applies_the_exception_at_once(client, settings):
    record = create(client)

    assert record["id"] == "appeal-0001"
    assert record["status"] == "exception_applied"
    exception = (settings.generated_dir / "appeal-0001-exception.rego").read_text(encoding="utf-8")
    assert 'input.user.id == "budi"' in exception
    assert 'input.resource.id == "candra"' in exception
    assert 'input.action == "read_grades"' in exception
    assert [e["event"] for e in record["history"]] == ["created", "exception_applied"]
    assert all(e["by"] == "admin_rina" for e in record["history"])


def test_appeal_lists_neighbours_and_candidates_narrowest_first(client):
    record = create(client)

    assert record["neighbours"]
    assert [c["index"] for c in record["candidates"]] == list(range(1, len(record["candidates"]) + 1))
    pairs = [c["pairs"] for c in record["candidates"]]
    assert pairs == sorted(pairs)
    assert HEAD_RULE in [c["pattern"] for c in record["candidates"]]


def test_appeals_get_increasing_ids_and_can_be_read_back(client):
    first, second = create(client), create(client)

    assert (first["id"], second["id"]) == ("appeal-0001", "appeal-0002")
    assert client.get("/corax/appeals/appeal-0002").json() == second


def test_small_rule_is_validated_and_written(client, settings):
    record = create(client)

    response = client.post(
        f"/corax/appeals/{record['id']}/confirm", json={"candidate": index_of(record, HEAD_RULE)}, headers=ADMIN
    )

    assert response.status_code == 200, response.json()
    confirmed = response.json()
    assert confirmed["status"] == "rule_applied"
    assert confirmed["chosen"]["scope"]["tier"] == "small"
    assert all(check["ok"] for check in confirmed["validation"])
    rule = (settings.generated_dir / "appeal-0001-rule.rego").read_text(encoding="utf-8")
    assert rule.startswith("package app.generated")
    assert '"head" in data.corax.graph[input.user.id]["holds"]' in rule
    assert confirmed["history"][-1] == {**confirmed["history"][-1], "event": "rule_applied", "by": "admin_rina"}


def test_large_rule_needs_acknowledgement(client, settings):
    record = create(client)
    broad = index_of(record, "user holds head")
    url = f"/corax/appeals/{record['id']}/confirm"

    refused = client.post(url, json={"candidate": broad})

    assert refused.status_code == 409
    assert refused.json()["scope"]["tier"] == "large"
    assert not (settings.generated_dir / "appeal-0001-rule.rego").exists()

    accepted = client.post(url, json={"candidate": broad, "acknowledge_scope": True})

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "rule_applied"


def test_admin_can_keep_only_the_exception(client, settings):
    record = create(client)

    response = client.post(f"/corax/appeals/{record['id']}/confirm", json={"candidate": None})

    assert response.json()["status"] == "exception_only"
    assert not (settings.generated_dir / "appeal-0001-rule.rego").exists()
    assert (settings.generated_dir / "appeal-0001-exception.rego").exists()


def test_an_appeal_is_confirmed_only_once(client):
    record = create(client)
    url = f"/corax/appeals/{record['id']}/confirm"
    client.post(url, json={"candidate": None})

    again = client.post(url, json={"candidate": 1})

    assert again.status_code == 409


def test_rule_that_fails_validation_is_not_written(client, settings, monkeypatch):
    import appeals

    monkeypatch.setattr(appeals, "render_rule", lambda *args, **kwargs: "package app.generated\n\nallow if true\n")
    record = create(client)

    response = client.post(
        f"/corax/appeals/{record['id']}/confirm", json={"candidate": index_of(record, HEAD_RULE)}
    )

    assert response.status_code == 422
    assert response.json()["validation"][-1] == {**response.json()["validation"][-1], "ok": False}
    assert client.get(f"/corax/appeals/{record['id']}").json()["status"] == "rule_rejected"
    assert not (settings.generated_dir / "appeal-0001-rule.rego").exists()


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({**APPEAL, "user": "nobody"}, 404),
        ({**APPEAL, "object": "nothing"}, 404),
        ({"user": "budi", "object": "candra"}, 422),
    ],
)
def test_invalid_appeals_are_rejected(client, body, status):
    assert client.post("/corax/appeals", json=body).status_code == status


@pytest.mark.parametrize("appeal_id", ["appeal-9999", "..%2Fsecret", "appeal 1"])
def test_unknown_or_invalid_appeal_ids_are_not_found(client, appeal_id):
    assert client.get(f"/corax/appeals/{appeal_id}").status_code == 404


def test_candidate_out_of_range_is_rejected(client):
    record = create(client)

    response = client.post(f"/corax/appeals/{record['id']}/confirm", json={"candidate": 99})

    assert response.status_code == 422


def test_appeals_are_disabled_without_graph_json(model_dir, settings):
    (model_dir / "graph.json").unlink()

    with TestClient(create_app(settings)) as client:
        assert client.post("/corax/appeals", json=APPEAL).status_code == 503
        assert client.get("/health").json()["appeals"] is False
        assert client.post("/risk", json={"user": "budi", "object": "ani"}).status_code == 200
