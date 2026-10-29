def suggestion(user, document, with_access=5):
    return {"user": user, "object": document, "risk": 0.1, "peers": {"with_access": with_access, "of": 10},
            "description": f"{with_access} of the 10 people most like {user} can open {document}."}  # fmt: skip


# --- suggested access (A) --------------------------------------------------------------------------


def test_the_admin_sees_suggestions_with_names_and_titles(client, corax, auth):
    corax.suggested = (200, {"items": [suggestion("employee_E002", "document_D099")]})

    found = client.get("/admin/suggestions", headers=auth("admin_01")).json()["suggestions"]

    assert [(s["user"], s["object"]) for s in found] == [("employee_E002", "document_D099")]
    assert found[0]["user_name"] and found[0]["document_title"] and found[0]["description"]
    assert corax.calls[-1][0] == "suggestions"


def test_a_dismissed_suggestion_is_not_shown_again(client, corax, auth):
    corax.suggested = (200, {"items": [suggestion("employee_E002", "document_D099"), suggestion("employee_E003", "document_D100")]})
    admin = auth("admin_01")

    client.post("/admin/suggestions/dismiss", json={"user": "employee_E002", "document": "document_D099"}, headers=admin)

    assert [s["user"] for s in client.get("/admin/suggestions", headers=admin).json()["suggestions"]] == ["employee_E003"]


def test_suggestions_are_for_admins_only(client, auth):
    assert client.get("/admin/suggestions", headers=auth("e002")).status_code == 403
    assert client.post("/admin/suggestions/dismiss", json={"user": "a", "document": "b"}, headers=auth("e002")).status_code == 403


def test_suggestions_fail_when_corax_does_not_answer(client, corax, auth):
    corax.suggested = (502, {"error": "Corax is not reachable"})

    assert client.get("/admin/suggestions", headers=auth("admin_01")).status_code == 502


# --- requests for a whole unit (C) -----------------------------------------------------------------


def test_units_are_departments_with_the_employees_own_first(client, auth):
    me = client.get("/me", headers=auth("e002")).json()

    units = client.get("/units", headers=auth("e002")).json()["units"]

    assert units[0] == me["department"] and sorted(units[1:]) == units[1:]


def test_an_employee_asks_for_a_unit_and_never_sees_its_documents(client, corax, auth):
    answer = client.post("/unit-requests", json={"unit": "finance", "reason": "grant budget of my program"}, headers=auth("e002"))

    assert answer.status_code == 201
    request = answer.json()
    assert (request["status"], request["unit"], request["given"]) == ("pending", "finance", 0)
    assert "documents" not in request
    assert client.post("/unit-requests", json={"unit": "nowhere"}, headers=auth("e002")).status_code == 422
    assert client.post("/unit-requests", json={"unit": "finance"}, headers=auth("admin_01")).status_code == 403


def test_the_admin_sees_the_unit_ranked_by_corax(client, corax, auth):
    request_id = client.post("/unit-requests", json={"unit": "finance"}, headers=auth("e002")).json()["id"]
    corax.ranked = (200, {"objects": [suggestion("employee_E002", "document_D099")], "warning": None})
    admin = auth("admin_01")

    answer = client.get(f"/admin/unit-requests/{request_id}/documents", headers=admin).json()

    assert [d["object"] for d in answer["documents"]] == ["document_D099"] and answer["documents"][0]["title"]
    assert corax.calls[-1] == ("rank", admin["Authorization"].removeprefix("Bearer "), "employee_E002", "owned_by", "department_finance")


def test_the_admin_gives_the_ticked_documents(client, corax, auth):
    request_id = client.post("/unit-requests", json={"unit": "finance", "reason": "budget"}, headers=auth("e002")).json()["id"]

    answer = client.post(f"/admin/unit-requests/{request_id}/grant", json={"documents": ["document_D099"]}, headers=auth("admin_01")).json()

    assert answer["request"]["status"] == "handled" and answer["request"]["documents"] == ["document_D099"]
    assert answer["granted"][0]["status"] == "granted" and answer["granted"][0]["requested_by"] == "admin_01"
    assert corax.calls[-1][2:] == ("employee_E002", "document_D099", f"unit request #{request_id}: budget")
    mine = client.get("/unit-requests", headers=auth("e002")).json()["requests"][0]
    assert (mine["status"], mine["given"]) == ("handled", 1) and "documents" not in mine
    assert client.post(f"/admin/unit-requests/{request_id}/grant", json={"documents": ["document_D099"]}, headers=auth("admin_01")).status_code == 409


def test_the_admin_rejects_a_unit_request(client, auth):
    request_id = client.post("/unit-requests", json={"unit": "finance"}, headers=auth("e002")).json()["id"]

    answer = client.post(f"/admin/unit-requests/{request_id}/reject", json={"note": "ask your head of program"}, headers=auth("admin_01"))

    assert answer.json()["request"]["status"] == "rejected"
    assert client.get("/unit-requests", headers=auth("e002")).json()["requests"][0]["note"] == "ask your head of program"


def test_unit_request_reviews_are_for_admins_only(client, auth):
    request_id = client.post("/unit-requests", json={"unit": "finance"}, headers=auth("e002")).json()["id"]
    employee = auth("e002")

    assert client.get("/admin/unit-requests", headers=employee).status_code == 403
    assert client.get(f"/admin/unit-requests/{request_id}/documents", headers=employee).status_code == 403
    assert client.post(f"/admin/unit-requests/{request_id}/grant", json={"documents": ["document_D099"]}, headers=employee).status_code == 403
