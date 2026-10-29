import pytest


@pytest.fixture
def requested(client, auth):
    """Employee E002 asks for document D099; returns the request."""
    answer = client.post("/access-requests/document_D099", json={"reason": "audit"}, headers=auth("e002"))
    assert answer.status_code == 201
    return answer.json()


def test_employee_asks_for_access(client, requested, auth):
    assert requested["status"] == "pending" and requested["reason"] == "audit"
    assert requested["user_id"] == "employee_E002" and requested["user_region"]

    again = client.post("/access-requests/document_D099", headers=auth("e002"))
    assert again.status_code == 409
    assert client.post("/access-requests/document_D099", headers=auth("admin_01")).status_code == 403


def test_a_pending_request_does_not_reveal_the_document(client, requested, auth):
    mine = client.get("/access-requests", headers=auth("e002")).json()["requests"][0]

    assert not any(k.startswith("document_") and k != "document_id" for k in requested)
    assert not any(k.startswith("document_") and k != "document_id" for k in mine)
    admin_view = client.get("/admin/access-requests", headers=auth("admin_01")).json()["requests"][0]
    assert admin_view["document_title"]


def test_asking_for_an_id_that_does_not_exist_looks_the_same(client, auth):
    unknown = client.post("/access-requests/document_D999", json={"reason": "x"}, headers=auth("e002"))
    known = client.post("/access-requests/document_D099", json={"reason": "x"}, headers=auth("e002"))

    assert unknown.status_code == known.status_code == 201
    assert unknown.json()["status"] == known.json()["status"] == "pending"
    assert [r["document_id"] for r in client.get("/admin/access-requests", headers=auth("admin_01")).json()["requests"]] == ["document_D099"]


def test_the_document_is_revealed_once_access_is_granted(client, granted, auth):
    mine = client.get("/access-requests", headers=auth("e002")).json()["requests"][0]

    assert mine["status"] == "granted" and mine["document_title"]


def test_employees_see_only_their_own_requests(client, requested, auth):
    assert [r["id"] for r in client.get("/access-requests", headers=auth("e002")).json()["requests"]] == [requested["id"]]
    assert client.get("/access-requests", headers=auth("e003")).json()["requests"] == []


def test_admin_endpoints_are_for_admins(client, requested, auth):
    employee = auth("e002")
    assert client.get("/admin/access-requests", headers=employee).status_code == 403
    for action in ("approve", "reject"):
        assert client.post(f"/admin/access-requests/{requested['id']}/{action}", headers=employee).status_code == 403

    admin = auth("admin_01")
    assert [r["id"] for r in client.get("/admin/access-requests", headers=admin).json()["requests"]] == [requested["id"]]
    assert client.get("/admin/access-requests", params={"status": "granted"}, headers=admin).json()["requests"] == []


def test_approve_starts_an_appeal_with_the_admins_token(client, corax, requested, auth):
    admin = auth("admin_01")

    answer = client.post(f"/admin/access-requests/{requested['id']}/approve", headers=admin)

    assert answer.status_code == 200
    request = answer.json()["request"]
    assert request["status"] == "granted" and request["appeal_id"] == "appeal-0001"
    assert request["decided_by"] == "admin_01" and request["candidates"][0]["index"] == 1
    token = admin["Authorization"].removeprefix("Bearer ")
    # only the appeal, with the admin's token: no pattern is applied until the admin picks one
    assert corax.calls == [("create", token, "employee_E002", "document_D099", "audit")]
    assert client.post(f"/admin/access-requests/{requested['id']}/approve", headers=admin).status_code == 409


def test_asking_calls_nothing_and_waits_for_an_admin(client, corax, requested):
    # the app has no Corax account of its own: nothing happens until an admin approves
    assert requested["status"] == "pending" and requested["decided_by"] is None
    assert corax.calls == []


def test_approving_applies_no_pattern_even_a_small_one(client, corax, requested, auth):
    corax.appeal = SMALL_APPEAL

    answer = client.post(f"/admin/access-requests/{requested['id']}/approve", headers=auth("admin_01")).json()

    assert answer["request"]["status"] == "granted" and answer["request"]["rule_pattern"] is None
    assert [call[0] for call in corax.calls] == ["create"]


def test_approve_when_the_user_can_read_it_already(client, corax, requested, auth):
    corax.appeal = (409, {"error": "employee_E002 already has access to document_D099: there is nothing to appeal"})

    request = client.post(f"/admin/access-requests/{requested['id']}/approve", headers=auth("admin_01")).json()["request"]

    assert request["status"] == "already_granted" and "already has access" in request["note"]


def test_approve_when_corax_fails(client, corax, requested, auth):
    corax.appeal = (503, {"error": "opa is not available"})
    admin = auth("admin_01")

    assert client.post(f"/admin/access-requests/{requested['id']}/approve", headers=admin).status_code == 502
    assert client.get("/admin/access-requests", headers=admin).json()["requests"][0]["status"] == "pending"


@pytest.fixture
def granted(client, requested, auth):
    client.post(f"/admin/access-requests/{requested['id']}/approve", headers=auth("admin_01"))
    return requested["id"]


def confirm(client, auth, request_id, candidate, acknowledge_scope=False):
    return client.post(f"/admin/access-requests/{request_id}/confirm", headers=auth("admin_01"),
                       json={"candidate": candidate, "acknowledge_scope": acknowledge_scope})  # fmt: skip


RULE = {"status": "rule_applied", "chosen": {"pattern": "user holds role_coordinator", "scope": {"tier": "small"}}}


def test_confirm_a_small_rule(client, corax, granted, auth):
    corax.answers[(1, False)] = (200, RULE)

    answer = confirm(client, auth, granted, 1)

    assert answer.status_code == 200
    request = answer.json()["request"]
    assert (request["status"], request["rule_pattern"], request["tier"]) == ("generalised", "user holds role_coordinator", "small")


def test_a_large_rule_needs_acknowledge_scope(client, corax, granted, auth):
    scope = {"tier": "large", "users": 30, "pairs": 400, "reasons": ["400 pairs > 50"]}
    corax.answers[(2, False)] = (409, {"error": "this rule has a large scope", "scope": scope})
    corax.answers[(2, True)] = (200, {**RULE, "chosen": {"pattern": "user works_in department_sales", "scope": scope}})

    first = confirm(client, auth, granted, 2)
    assert first.status_code == 409 and first.json()["appeal"]["scope"] == scope
    assert first.json()["request"]["status"] == "granted"

    second = confirm(client, auth, granted, 2, acknowledge_scope=True)
    assert second.status_code == 200 and second.json()["request"]["tier"] == "large"


def test_keep_only_the_exception(client, corax, granted, auth):
    corax.answers[(None, False)] = (200, {"status": "exception_only"})

    assert confirm(client, auth, granted, None).json()["request"]["status"] == "exception_only"


def test_a_rule_that_fails_validation_keeps_the_exception(client, corax, granted, auth):
    corax.answers[(1, False)] = (422, {"error": "the rule failed validation", "validation": []})

    answer = confirm(client, auth, granted, 1)

    assert answer.status_code == 422 and answer.json()["request"]["status"] == "granted"


def test_confirm_only_granted_and_reject_only_pending(client, requested, auth):
    admin = auth("admin_01")
    assert confirm(client, auth, requested["id"], 1).status_code == 409

    rejected = client.post(f"/admin/access-requests/{requested['id']}/reject", json={"note": "not needed"}, headers=admin)
    assert rejected.json()["request"]["status"] == "rejected" and rejected.json()["request"]["note"] == "not needed"
    assert client.post(f"/admin/access-requests/{requested['id']}/reject", headers=admin).status_code == 409
    assert client.post("/admin/access-requests/999/approve", headers=admin).status_code == 404


SMALL = {"tier": "small", "users": 4, "pairs": 10, "mean_risk": 0.11, "reasons": []}
SMALL_APPEAL = (201, {"id": "appeal-0001", "status": "exception_applied",
                      "candidates": [{"index": 1, "pattern": "user holds role_coordinator", "scope": SMALL}]})  # fmt: skip


def test_no_account_signs_in_without_being_a_person(client):
    assert client.post("/auth/login", json={"username": "docapp", "password": "corax-demo"}).status_code == 401


def test_an_admin_revokes_the_rule_through_corax(client, corax, requested, auth):
    corax.appeal = SMALL_APPEAL
    corax.answers[(1, False)] = (200, RULE)
    admin = auth("admin_01")
    client.post(f"/admin/access-requests/{requested['id']}/approve", headers=admin)
    confirm(client, auth, requested["id"], 1)

    answer = client.post(f"/admin/access-requests/{requested['id']}/revoke", headers=admin)

    assert answer.status_code == 200
    assert answer.json()["request"]["status"] == "rule_revoked"
    assert answer.json()["request"]["note"].startswith("Revoked by admin_01 on ")
    assert corax.calls[-1] == ("revoke", admin["Authorization"].removeprefix("Bearer "), "appeal-0001", False)


def test_revoking_the_exception_too_takes_back_all_access(client, corax, requested, auth):
    admin = auth("admin_01")
    client.post(f"/admin/access-requests/{requested['id']}/approve", headers=admin)

    answer = client.post(f"/admin/access-requests/{requested['id']}/revoke", json={"exception": True}, headers=admin)

    assert answer.json()["request"]["status"] == "revoked"
    assert corax.calls[-1][-1] is True


def test_only_admins_revoke_and_only_what_was_granted(client, corax, requested, auth):
    assert client.post(f"/admin/access-requests/{requested['id']}/revoke", headers=auth("e002")).status_code == 403
    assert client.post(f"/admin/access-requests/{requested['id']}/revoke", headers=auth("admin_01")).status_code == 409
    assert client.post("/admin/access-requests/999/revoke", headers=auth("admin_01")).status_code == 404


def test_nothing_left_to_revoke_is_passed_on(client, corax, requested, auth):
    admin = auth("admin_01")
    client.post(f"/admin/access-requests/{requested['id']}/approve", headers=admin)
    corax.revoked = (409, {"error": "appeal appeal-0001 has nothing active to revoke"})

    answer = client.post(f"/admin/access-requests/{requested['id']}/revoke", headers=admin)

    assert answer.status_code == 409
    assert answer.json()["request"]["status"] == "granted"


# --- the admin gives access without being asked ----------------------------------------------------


def test_an_admin_grants_a_document_without_a_request(client, corax, auth):
    admin = auth("admin_01")

    answer = client.post("/admin/grants", json={"user": "employee_E002", "document": "document_D099", "reason": "new in the team"}, headers=admin)

    assert answer.status_code == 201
    request = answer.json()["request"]
    assert (request["status"], request["requested_by"], request["decided_by"]) == ("granted", "admin_01", "admin_01")
    assert corax.calls == [("create", admin["Authorization"].removeprefix("Bearer "), "employee_E002", "document_D099", "new in the team")]
    mine = client.get("/access-requests", headers=auth("e002")).json()["requests"]
    assert [r["document_id"] for r in mine] == ["document_D099"] and mine[0]["document_title"]


def test_a_grant_then_follows_the_same_choice_of_a_rule(client, corax, auth):
    corax.answers[(1, False)] = (200, RULE)
    request_id = client.post("/admin/grants", json={"user": "employee_E002", "document": "document_D099"}, headers=auth("admin_01")).json()["request"]["id"]

    assert confirm(client, auth, request_id, 1).json()["request"]["status"] == "generalised"


def test_only_admins_grant_and_only_to_known_employees_and_documents(client, auth):
    body = {"user": "employee_E002", "document": "document_D099"}
    assert client.post("/admin/grants", json=body, headers=auth("e002")).status_code == 403
    assert client.get("/admin/employees", headers=auth("e002")).status_code == 403
    assert client.post("/admin/grants", json={**body, "user": "admin_01"}, headers=auth("admin_01")).status_code == 404
    assert client.post("/admin/grants", json={**body, "document": "document_D999"}, headers=auth("admin_01")).status_code == 404


def test_a_grant_corax_refuses_leaves_no_request(client, corax, auth):
    corax.appeal = (503, {"error": "opa is not available"})
    admin = auth("admin_01")

    assert client.post("/admin/grants", json={"user": "employee_E002", "document": "document_D099"}, headers=admin).status_code == 502
    assert client.get("/admin/access-requests", headers=admin).json()["requests"] == []


def test_the_admin_lists_employees_without_passwords(client, auth):
    employees = client.get("/admin/employees", headers=auth("admin_01")).json()["employees"]

    assert employees and all(e["id"].startswith("employee_") and "password" not in e for e in employees)


def test_give_access_lists_only_documents_the_employee_cannot_open(client, auth, opa):
    opa.allowed = {"document_D001"}

    documents = client.get("/admin/employees/employee_E002/documents", headers=auth("admin_01")).json()["documents"]

    ids = [d["id"] for d in documents]
    assert "document_D001" not in ids and "document_D002" in ids and len(ids) == 159
    assert opa.calls[-1][:3] == ("employee_E002", "read", "document")


def test_documents_to_give_are_for_admins_and_known_employees(client, auth, opa):
    assert client.get("/admin/employees/employee_E002/documents", headers=auth("e002")).status_code == 403
    assert client.get("/admin/employees/admin_01/documents", headers=auth("admin_01")).status_code == 404
    from docapp.opa import OpaError

    opa.error = OpaError("OPA is not reachable")
    assert client.get("/admin/employees/employee_E002/documents", headers=auth("admin_01")).status_code == 503
