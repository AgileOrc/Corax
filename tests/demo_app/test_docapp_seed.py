from docapp import db
from docapp.main import create_app
from docapp.seed import read_graph
from fastapi.testclient import TestClient


def test_accounts_and_documents_from_the_graph(client, settings, seed_dir):
    types, facts = read_graph(seed_dir)
    with db.session(settings.database) as c:
        users = c.execute("SELECT kind, COUNT(*) FROM users GROUP BY kind").fetchall()
        assert dict(users) == {"admin": 1, "employee": sum(t == "employee" for t in types.values())}
        assert c.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == sum(t == "document" for t in types.values())

        employee = db.user(c, "employee_E013")
        assert employee["projects"] == sorted(p.split("_", 1)[1] for p in facts["employee_E013"]["works_on"])
        assert employee["manager"] == facts["employee_E013"]["reports_to"][0]
        document = db.document(c, "document_D001")
        assert len(document["projects"]) == 2 and document["content"]


def test_passwords_are_hashed(settings, client, password):
    with db.session(settings.database) as c:
        stored = [row[0] for row in c.execute("SELECT password FROM users")]
    assert all(p.startswith("pbkdf2_sha256$") and password not in p for p in stored)
    assert len(set(stored)) == len(stored)  # one salt per account


def test_seeds_once_and_the_same_every_time(settings, corax, opa, client, auth):
    headers = auth("e001")
    client.post("/access-requests/document_D099", headers=headers)
    name = client.get("/me", headers=headers).json()["name"]

    with TestClient(create_app(settings, corax, opa)) as again:  # a restart on the same database
        headers = auth(via=again, username="e001")
        assert again.get("/me", headers=headers).json()["name"] == name
        assert len(again.get("/access-requests", headers=headers).json()["requests"]) == 1
