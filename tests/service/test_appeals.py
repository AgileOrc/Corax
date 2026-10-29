import json
import time

import jwt
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
SECRET = "test-secret-with-enough-length-for-hs256"


def bearer(user):
    claims = {"sub": user, "iss": "test-issuer", "aud": "test-api", "exp": int(time.time()) + 300}
    return {"Authorization": f"Bearer {jwt.encode(claims, SECRET, algorithm='HS256')}"}


ADMIN = bearer("admin_rina")
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
def corax_config(tmp_path):
    config = {
        "corax": {
            "config": {
                "jwt": {"secret": SECRET, "iss": "test-issuer", "aud": "test-api"},
                "admin": {"users": ["admin_rina"]},
            }
        }
    }
    path = tmp_path / "data.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


@pytest.fixture
def settings(model_dir, tmp_path, opa, corax_config):
    return Settings(
        model_dir=model_dir,
        corax_config=corax_config,
        opa_path=opa,
        generated_dir=tmp_path / "generated",
        appeals_dir=tmp_path / "appeals",
        tier_limits=TierLimits(max_user_share=1.0, max_pairs=1, max_mean_risk=1.0),
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings), headers=ADMIN) as client:
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
    assert 'input.resource.type == "student"' in exception
    assert [e["event"] for e in record["history"]] == ["created", "exception_applied"]
    assert all(e["by"] == "admin_rina" for e in record["history"])


def test_appeal_lists_neighbours_and_candidates_narrowest_first(client):
    record = create(client)

    assert record["neighbours"]
    assert [c["index"] for c in record["candidates"]] == list(range(1, len(record["candidates"]) + 1))
    pairs = [c["pairs"] for c in record["candidates"]]
    assert pairs == sorted(pairs)
    assert HEAD_RULE in [c["pattern"] for c in record["candidates"]]


def test_candidates_and_the_exception_read_as_plain_sentences(client):
    record = create(client)

    head = next(c for c in record["candidates"] if c["pattern"] == HEAD_RULE)
    assert head["description"].startswith("A lecturer may read_grades a student when ")
    assert "the lecturer holds head" in head["description"]
    assert record["exception"]["description"] == "budi may read_grades candra, an exception for this one student only."


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
    assert 'input.resource.type == "student"' in rule
    assert [check["name"] for check in confirmed["validation"]][-1] == "resource type"
    assert f"# description: {json.dumps(confirmed['chosen']['description'])}" in rule
    assert f"#   pattern: {json.dumps(HEAD_RULE)}" in rule
    assert confirmed["history"][-1] == {**confirmed["history"][-1], "event": "rule_applied", "by": "admin_rina"}


def test_large_rule_needs_acknowledgement(client, settings):
    record = create(client)
    broad = index_of(record, "user holds head")
    url = f"/corax/appeals/{record['id']}/confirm"

    refused = client.post(url, json={"candidate": broad})

    assert refused.status_code == 409
    assert refused.json()["scope"]["tier"] == "large"
    assert not (settings.generated_dir / "appeal-0001-rule.rego").exists()

    assert refused.json()["description"].startswith("A lecturer may read_grades a student when ")
    assert refused.json()["affected"] == {
        "users": 2,
        "objects": 3,
        "pairs": 4,
        "by_user": [{"user": "budi", "objects": ["dewi"]}, {"user": "sari", "objects": ["ani", "candra", "dewi"]}],
        "more_users": 0,
    }

    accepted = client.post(url, json={"candidate": broad, "acknowledge_scope": True})

    assert accepted.status_code == 200
    assert accepted.json()["status"] == "rule_applied"


def test_preview_lists_who_would_gain_access_and_writes_nothing(client, settings):
    record = create(client)
    head = index_of(record, HEAD_RULE)

    preview = client.get(f"/corax/appeals/{record['id']}/candidates/{head}")

    assert preview.status_code == 200, preview.json()
    assert preview.json()["pattern"] == HEAD_RULE
    assert preview.json()["affected"]["by_user"] == [{"user": "sari", "objects": ["dewi"]}]
    assert preview.json()["scope"]["pairs"] == 1
    assert not (settings.generated_dir / "appeal-0001-rule.rego").exists()
    assert client.get(f"/corax/appeals/{record['id']}").json()["status"] == "exception_applied"


@pytest.mark.parametrize("candidate", [0, 99])
def test_preview_of_an_unknown_candidate_is_not_found(client, candidate):
    record = create(client)

    assert client.get(f"/corax/appeals/{record['id']}/candidates/{candidate}").status_code == 404


def test_affected_lists_a_limited_number_of_users():
    from appeals import affected

    pairs = [(f"user_{i}", "report") for i in range(5)] + [("user_0", "other")]

    result = affected(pairs, limit=2)

    assert result["users"] == 5
    assert result["objects"] == 2
    assert result["by_user"] == [{"user": "user_0", "objects": ["other", "report"]}, {"user": "user_1", "objects": ["report"]}]
    assert result["more_users"] == 3


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


def test_accepting_writes_a_snapshot_of_who_gained_access(client, settings):
    record = create(client)
    client.post(f"/corax/appeals/{record['id']}/confirm", json={"candidate": index_of(record, HEAD_RULE)})

    snapshot = json.loads((settings.appeals_dir / "appeal-0001-granted.json").read_text(encoding="utf-8"))

    assert snapshot["exception"]["access"]["by_user"] == [{"user": "budi", "objects": ["candra"]}]
    assert snapshot["rule"]["access"]["by_user"] == [{"user": "sari", "objects": ["dewi"]}]
    assert snapshot["rule"]["approved_by"] == "admin_rina"
    assert snapshot["rule"]["description"].startswith("A lecturer may read_grades a student when ")
    assert snapshot["rule"]["revoked"] is None


def test_keeping_only_the_exception_has_no_rule_in_the_snapshot(client, settings):
    record = create(client)
    client.post(f"/corax/appeals/{record['id']}/confirm", json={"candidate": None})

    snapshot = json.loads((settings.appeals_dir / "appeal-0001-granted.json").read_text(encoding="utf-8"))

    assert set(snapshot) == {"exception"}


def test_revoke_deletes_the_rule_and_records_who_did_it(client, settings):
    record = create(client)
    client.post(f"/corax/appeals/{record['id']}/confirm", json={"candidate": index_of(record, HEAD_RULE)})

    response = client.post(f"/corax/appeals/{record['id']}/revoke", json={})

    assert response.status_code == 200, response.json()
    assert response.json()["status"] == "rule_revoked"
    assert response.json()["history"][-1] == {**response.json()["history"][-1], "event": "rule_revoked", "by": "admin_rina"}
    assert not (settings.generated_dir / "appeal-0001-rule.rego").exists()
    assert (settings.generated_dir / "appeal-0001-exception.rego").exists()
    snapshot = json.loads((settings.appeals_dir / "appeal-0001-granted.json").read_text(encoding="utf-8"))
    assert snapshot["rule"]["revoked"]["by"] == "admin_rina"
    assert snapshot["exception"]["revoked"] is None

    again = client.post(f"/corax/appeals/{record['id']}/revoke", json={})

    assert again.status_code == 409


def test_revoke_can_also_remove_the_exception(client, settings):
    record = create(client)
    client.post(f"/corax/appeals/{record['id']}/confirm", json={"candidate": None})

    assert client.post(f"/corax/appeals/{record['id']}/revoke", json={}).status_code == 409
    response = client.post(f"/corax/appeals/{record['id']}/revoke", json={"exception": True})

    assert response.status_code == 200
    assert not (settings.generated_dir / "appeal-0001-exception.rego").exists()
    assert response.json()["history"][-1]["event"] == "exception_revoked"


def usage(settings, appeal_id="appeal-0001"):
    path = settings.appeals_dir / f"{appeal_id}-usage.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def accept_head_rule(client):
    record = create(client)
    client.post(f"/corax/appeals/{record['id']}/confirm", json={"candidate": index_of(record, HEAD_RULE)})
    return record


@pytest.fixture
def trusting_client(settings):
    # Every pair is low risk, so every /risk call is an allowed request.
    with TestClient(create_app(Settings(**{**settings.__dict__, "risk_threshold": 1.0})), headers=ADMIN) as client:
        yield client


def test_using_access_from_a_rule_is_logged(trusting_client, settings):
    accept_head_rule(trusting_client)

    trusting_client.post("/risk", json={"user": "sari", "object": "dewi", "action": "read_grades"})

    assert [(u["user"], u["object"], u["via"]) for u in usage(settings)] == [("sari", "dewi", "rule")]


def test_using_the_exception_is_logged_through_usage(trusting_client, settings):
    accept_head_rule(trusting_client)

    response = trusting_client.post("/usage", json={"user": "budi", "object": "candra", "action": "read_grades"})

    assert response.json() == {"logged": ["appeal-0001"]}
    assert [(u["user"], u["object"], u["via"]) for u in usage(settings)] == [("budi", "candra", "exception")]


@pytest.mark.parametrize(
    "body",
    [
        {"user": "andi", "object": "dewi", "action": "read_grades"},
        {"user": "sari", "object": "dewi", "action": "read_profile"},
        {"user": "budi", "object": "candra", "action": "read_grades"},
    ],
)
def test_access_not_granted_by_a_rule_is_not_logged(trusting_client, settings, body):
    accept_head_rule(trusting_client)

    trusting_client.post("/risk", json=body)

    assert usage(settings) == []


def test_a_high_risk_request_is_not_logged(settings):
    with TestClient(create_app(Settings(**{**settings.__dict__, "risk_threshold": 0.0})), headers=ADMIN) as client:
        accept_head_rule(client)
        client.post("/risk", json={"user": "sari", "object": "dewi", "action": "read_grades"})

    assert usage(settings) == []


def test_revoked_access_is_no_longer_logged(trusting_client, settings):
    accept_head_rule(trusting_client)
    trusting_client.post("/corax/appeals/appeal-0001/revoke", json={})

    trusting_client.post("/risk", json={"user": "sari", "object": "dewi", "action": "read_grades"})

    assert usage(settings) == []


def test_usage_is_still_logged_after_a_restart(trusting_client, settings):
    accept_head_rule(trusting_client)
    restarted = Settings(**{**settings.__dict__, "risk_threshold": 1.0})

    with TestClient(create_app(restarted)) as client:
        client.post("/risk", json={"user": "sari", "object": "dewi", "action": "read_grades"})

    assert len(usage(settings)) == 1


def test_rules_show_who_gained_access_and_how_it_was_used(trusting_client):
    accept_head_rule(trusting_client)
    trusting_client.post("/risk", json={"user": "sari", "object": "dewi", "action": "read_grades"})

    rules = trusting_client.get("/corax/rules").json()

    assert [(r["appeal"], r["kind"]) for r in rules] == [("appeal-0001", "rule"), ("appeal-0001", "exception")]
    rule = rules[0]
    assert rule["approved_by"] == "admin_rina"
    assert rule["file_missing"] is False
    assert rule["access"]["by_user"] == [{"user": "sari", "objects": ["dewi"]}]
    assert rule["usage"]["uses"] == 1
    assert rule["usage"]["by_user"] == [{"user": "sari", "objects": {"dewi": 1}}]
    assert [(u["user"], u["object"], u["action"]) for u in rule["uses"]] == [("sari", "dewi", "read_grades")]
    assert rule["summary"][0] == rule["description"]
    assert rule["summary"][1].startswith("Approved as a rule by admin_rina on ")
    assert rule["summary"][2] == "1 person gained access to 1 student."
    assert rule["summary"][3] == "Used 1 time by 1 person:"
    assert rule["summary"][4].endswith("sari read_grades dewi")
    assert rules[1]["summary"][-1] == "Not used yet."


def test_rules_leave_out_revoked_access_and_flag_missing_files(client, settings):
    accept_head_rule(client)
    client.post("/corax/appeals/appeal-0001/revoke", json={})
    (settings.generated_dir / "appeal-0001-exception.rego").unlink()

    rules = client.get("/corax/rules").json()

    assert [r["kind"] for r in rules] == ["exception"]
    assert rules[0]["file_missing"] is True
    assert "not revoked through Corax" in rules[0]["summary"][3]


def test_a_user_lists_only_their_own_access(client):
    accept_head_rule(client)

    sari = client.get("/corax/me/access", headers=bearer("sari"))
    budi = client.get("/corax/me/access", headers=bearer("budi"))
    andi = client.get("/corax/me/access", headers=bearer("andi"))

    assert sari.json() == {"user": "sari", "resources": ["dewi"]}
    assert budi.json() == {"user": "budi", "resources": ["candra"]}
    assert andi.json() == {"user": "andi", "resources": []}


def test_own_access_ignores_any_user_in_the_request(client):
    accept_head_rule(client)

    response = client.get(
        "/corax/me/access?user=sari", headers={**bearer("andi"), "x-corax-user": "sari"}
    )

    assert response.json() == {"user": "andi", "resources": []}


def test_revoked_access_disappears_from_the_users_list(client):
    accept_head_rule(client)
    client.post("/corax/appeals/appeal-0001/revoke", json={})

    assert client.get("/corax/me/access", headers=bearer("sari")).json()["resources"] == []


def test_rules_and_own_access_need_a_token(settings):
    with TestClient(create_app(settings)) as anonymous:
        assert anonymous.get("/corax/rules").status_code == 401
        assert anonymous.get("/corax/rules", headers=bearer("bob")).status_code == 403
        assert anonymous.get("/corax/me/access").status_code == 401
        assert anonymous.get("/corax/me/access", headers=bearer("bob")).status_code == 200


@pytest.mark.parametrize("appeal_id", ["appeal-9999", "..%2Fsecret", "appeal 1", "appeal-0001-granted"])
def test_unknown_or_invalid_appeal_ids_are_not_found(client, appeal_id):
    assert client.get(f"/corax/appeals/{appeal_id}").status_code == 404


def test_candidate_out_of_range_is_rejected(client):
    record = create(client)

    response = client.post(f"/corax/appeals/{record['id']}/confirm", json={"candidate": 99})

    assert response.status_code == 422


def test_appeals_are_disabled_without_graph_json(model_dir, settings):
    (model_dir / "graph.json").unlink()

    with TestClient(create_app(settings), headers=ADMIN) as client:
        assert client.post("/corax/appeals", json=APPEAL).status_code == 503
        assert client.get("/health").json()["appeals"] is False
        assert client.post("/risk", json={"user": "budi", "object": "ani"}).status_code == 200


def test_appeals_require_an_admin_token(settings):
    with TestClient(create_app(settings)) as anonymous:
        assert anonymous.post("/corax/appeals", json=APPEAL).status_code == 401
        assert anonymous.get("/corax/appeals/appeal-0001").status_code == 401
        assert anonymous.post("/corax/appeals/appeal-0001/confirm", json={}).status_code == 401
        assert anonymous.get("/corax/appeals/appeal-0001/candidates/1").status_code == 401
        assert anonymous.get("/corax/appeals/appeal-0001/candidates/1", headers=bearer("bob")).status_code == 403
        assert anonymous.post("/corax/appeals/appeal-0001/revoke", json={}, headers=bearer("bob")).status_code == 403
        assert anonymous.post("/corax/appeals", json=APPEAL, headers=bearer("bob")).status_code == 403
    assert not (settings.generated_dir).exists()


def test_a_forged_identity_header_is_ignored(settings):
    with TestClient(create_app(settings)) as client:
        spoofed = {**bearer("bob"), "x-corax-user": "admin_rina"}
        assert client.post("/corax/appeals", json=APPEAL, headers=spoofed).status_code == 403

        record = client.post("/corax/appeals", json=APPEAL, headers={**ADMIN, "x-corax-user": "mallory"}).json()
        assert {e["by"] for e in record["history"]} == {"admin_rina"}


def test_appeals_fail_closed_without_corax_config(settings):
    unconfigured = Settings(**{**settings.__dict__, "corax_config": None})

    with TestClient(create_app(unconfigured), headers=ADMIN) as client:
        assert client.post("/corax/appeals", json=APPEAL).status_code == 503
        assert client.post("/risk", json={"user": "budi", "object": "ani"}).status_code == 200


# --- suggested access and requests for a unit ------------------------------------------------------


def test_rank_lists_the_unit_most_covered_by_peers_first(client):
    ranked = client.post("/corax/rank", json={"user": "sari", "relation": "member_of", "node": "IF"}).json()

    assert [o["object"] for o in ranked["objects"]][0] == "ani"
    assert ranked["objects"][0]["peers"]["with_access"] == 1 and ranked["warning"] is None
    assert ranked["objects"][0]["description"].endswith("people most like sari can open ani.")


def test_rank_leaves_out_what_the_user_can_reach_and_warns_without_peers(client):
    ranked = client.post("/corax/rank", json={"user": "budi", "relation": "member_of", "node": "IF"}).json()

    assert [o["object"] for o in ranked["objects"]] == ["candra"]
    assert "Check that this is the right unit" in ranked["warning"]


def test_access_granted_by_an_appeal_is_not_suggested_again(client):
    accept_head_rule(client)

    ranked = client.post("/corax/rank", json={"user": "sari", "relation": "member_of", "node": "SI"}).json()

    assert "dewi" not in [o["object"] for o in ranked["objects"]]


def test_suggestions_have_low_risk_and_a_sentence(trusting_client):
    found = trusting_client.get("/corax/suggestions").json()

    assert all(s["risk"] <= 1.0 and s["description"].count(" people most like ") == 1 for s in found)
    assert trusting_client.get("/corax/suggestions", params={"user": "nobody"}).status_code == 404


def test_suggestions_and_rank_are_for_admins(settings):
    with TestClient(create_app(settings)) as anonymous:
        assert anonymous.get("/corax/suggestions").status_code == 401
        assert anonymous.get("/corax/suggestions", headers=bearer("bob")).status_code == 403
        body = {"user": "sari", "relation": "member_of", "node": "IF"}
        assert anonymous.post("/corax/rank", json=body, headers=bearer("bob")).status_code == 403


# --- dry run, access already held, resource type ---------------------------------------------------


def test_appeal_for_access_already_held_is_refused(client, settings):
    # budi already reads ani: an exception or a rule would change nothing
    response = client.post("/corax/appeals", json={**APPEAL, "object": "ani"})

    assert response.status_code == 409
    assert not settings.generated_dir.exists()


def test_dry_run_reports_without_writing(client, settings):
    response = client.post("/corax/appeals", json={**APPEAL, "dry_run": True})

    assert response.status_code == 200, response.json()
    preview = response.json()
    assert preview["dry_run"] is True and "id" not in preview
    assert preview["appeal"] == {k: APPEAL[k] for k in ("user", "object", "action", "reason")}
    assert 0.0 <= preview["risk"] <= 1.0 and isinstance(preview["high_risk"], bool)
    assert preview["scope"]["tier"] in ("small", "large") and preview["scope"]["pairs"] == preview["candidates"][0]["pairs"]
    assert not settings.generated_dir.exists() and not settings.appeals_dir.exists()
    # the same candidates an appeal finds, and the first appeal still gets the first id
    assert create(client)["candidates"] == preview["candidates"]
    assert create(client)["id"] == "appeal-0002"


def test_dry_run_scope_matches_the_tier_check_of_confirm(client):
    preview = client.post("/corax/appeals", json={**APPEAL, "dry_run": True}).json()
    record = create(client)

    confirmed = client.post(f"/corax/appeals/{record['id']}/confirm", json={"candidate": 1})

    if preview["scope"]["tier"] == "small":
        assert confirmed.json()["chosen"]["scope"] == preview["scope"]
    else:
        assert confirmed.status_code == 409 and confirmed.json()["scope"] == preview["scope"]


def test_every_candidate_has_its_scope_and_nothing_is_picked_for_the_admin(client):
    preview = client.post("/corax/appeals", json={**APPEAL, "dry_run": True}).json()
    record = create(client)

    assert all(c["scope"]["tier"] in ("small", "large") for c in preview["candidates"])
    assert preview["scope"] == preview["candidates"][0]["scope"]
    assert "auto_apply" not in preview and "auto_apply" not in record


def test_dry_run_is_refused_like_an_appeal(client, settings):
    assert client.post("/corax/appeals", json={**APPEAL, "object": "ani", "dry_run": True}).status_code == 409
    with TestClient(create_app(settings)) as anonymous:
        assert anonymous.post("/corax/appeals", json={**APPEAL, "dry_run": True}).status_code == 401


def test_a_dry_run_writes_no_snapshot(client, settings):
    client.post("/corax/appeals", json={**APPEAL, "dry_run": True})

    assert not (settings.appeals_dir / "appeal-0001-granted.json").exists()


def test_resource_type_can_be_configured(settings):
    named = Settings(**{**settings.__dict__, "resource_type": "transcript"})

    with TestClient(create_app(named), headers=ADMIN) as client:
        record = client.post("/corax/appeals", json=APPEAL).json()

    exception = (settings.generated_dir / f"{record['id']}-exception.rego").read_text(encoding="utf-8")
    assert 'input.resource.type == "transcript"' in exception


def test_each_candidate_counts_the_similar_cases_it_covers(client):
    preview = client.post("/corax/appeals", json={**APPEAL, "dry_run": True}).json()

    for c in preview["candidates"]:
        assert 1 <= c["similar"]["of"] <= 30 and c["similar"]["covered"] == round(c["support"] * c["similar"]["of"])
    assert len({c["similar"]["of"] for c in preview["candidates"]}) == 1
