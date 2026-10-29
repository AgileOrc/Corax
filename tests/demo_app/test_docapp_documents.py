def test_catalog_lists_every_document_without_content(client, auth):
    body = client.get("/documents", headers=auth("e001")).json()

    assert body["count"] == len(body["documents"]) == 160
    assert all("content" not in d and len(d["projects"]) == 2 for d in body["documents"])


def test_catalog_lists_only_what_the_policy_lets_the_employee_open(client, auth, opa):
    opa.allowed = {"document_D001", "document_D002"}

    body = client.get("/documents", headers=auth("e001")).json()

    assert [d["id"] for d in body["documents"]] == ["document_D001", "document_D002"] and body["count"] == 2
    user, action, resource_type, objects = opa.calls[-1]
    assert (user, action, resource_type, len(objects)) == ("employee_E001", "read", "document", 160)


def test_a_search_never_finds_a_document_the_employee_may_not_open(client, auth, opa):
    opa.allowed = {"document_D002"}

    assert client.get("/documents", params={"q": "d001"}, headers=auth("e001")).json()["documents"] == []


def test_admins_see_every_document_to_grant_access(client, auth, opa):
    opa.allowed = set()

    assert client.get("/documents", headers=auth("admin_01")).json()["count"] == 160
    assert opa.calls == []


def test_the_catalog_fails_closed_when_opa_does_not_answer(client, auth, opa):
    from docapp.opa import OpaError

    opa.error = OpaError("OPA is not reachable")

    answer = client.get("/documents", headers=auth("e001"))

    assert answer.status_code == 503 and "documents" not in answer.json()


def test_catalog_filters(client, auth):
    headers = auth("e001")

    finance = client.get("/documents", params={"department": "finance"}, headers=headers).json()["documents"]
    assert finance and all(d["department"] == "finance" for d in finance)
    secret = client.get("/documents", params={"classification": "confidential"}, headers=headers).json()["documents"]
    assert secret and all(d["classification"] == "confidential" for d in secret)
    one = client.get("/documents", params={"q": "d001"}, headers=headers).json()["documents"]
    assert [d["id"] for d in one] == ["document_D001"]


def test_in_my_projects_is_a_hint_from_the_projects(client, auth):
    headers = auth("e001")
    mine = set(client.get("/me", headers=headers).json()["projects"])

    for document in client.get("/documents", headers=headers).json()["documents"]:
        assert document["in_my_projects"] == bool(mine & set(document["projects"]))


def test_read_a_document(client, auth):
    headers = auth("e001")

    document = client.get("/documents/document_D001", headers=headers).json()
    assert document["id"] == "document_D001" and "Classification" in document["content"]
    assert client.get("/documents/document_D999", headers=headers).status_code == 404


def test_summary_is_the_first_paragraph_only(client, auth):
    headers = auth("e001")

    summary = client.get("/documents/document_D001/summary", headers=headers).json()
    full = client.get("/documents/document_D001", headers=headers).json()
    assert summary["title"] == full["title"] and "content" not in summary
    assert summary["summary"] == full["content"].split("\n\n")[0]
    assert (summary["site"], summary["region"]) == (full["site"], full["region"]) and summary["region"]
    assert client.get("/documents/document_D999/summary", headers=headers).status_code == 404
