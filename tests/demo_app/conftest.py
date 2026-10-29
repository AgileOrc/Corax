import json

import make_enterprise
import pytest
from docapp.main import create_app
from docapp.settings import Settings
from fastapi.testclient import TestClient

PASSWORD = "corax-demo"
JWT = {"secret": "test-secret-of-the-document-app-tests", "iss": "corax-test", "aud": "corax-test-api"}


class FakeCorax:
    """Stands in for Corax's appeal API: records the calls, answers what the test sets."""

    def __init__(self):
        self.calls = []
        # by default the only pattern is large: confirming it needs acknowledge_scope
        self.appeal = (201, {"id": "appeal-0001", "status": "exception_applied", "candidates": [CANDIDATE]})
        # (candidate, acknowledge_scope) -> (status, body)
        self.answers = {(1, False): (409, {"error": "this rule has a large scope", "scope": LARGE})}

    def create_appeal(self, token, user, document, reason):
        self.calls.append(("create", token, user, document, reason))
        return self.appeal

    def confirm(self, token, appeal_id, candidate, acknowledge_scope):
        self.calls.append(("confirm", token, appeal_id, candidate, acknowledge_scope))
        return self.answers[(candidate, acknowledge_scope)]

    def revoke(self, token, appeal_id, exception):
        self.calls.append(("revoke", token, appeal_id, exception))
        return self.revoked

    revoked = (200, {"id": "appeal-0001", "status": "rule_revoked"})

    def suggestions(self, token, limit):
        self.calls.append(("suggestions", token, limit))
        return self.suggested

    suggested = (200, {"items": []})

    def rank(self, token, user, relation, node):
        self.calls.append(("rank", token, user, relation, node))
        return self.ranked

    ranked = (200, {"objects": [], "warning": None})


class FakeOpa:
    """Stands in for OPA's allowed_objects: every document by default, or the ones the test sets."""

    def __init__(self):
        self.calls = []
        self.allowed = None  # None: every object
        self.error = None

    def allowed_objects(self, user, action, resource_type, objects):
        self.calls.append((user, action, resource_type, list(objects)))
        if self.error:
            raise self.error
        return set(objects) if self.allowed is None else set(objects) & self.allowed


LARGE = {"tier": "large", "users": 24, "pairs": 71, "mean_risk": 0.1, "reasons": ["24 users > 5", "71 pairs > 50"]}
CANDIDATE = {"index": 1, "pattern": "user holds role_coordinator", "scope": LARGE}


@pytest.fixture(scope="session")
def seed_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("enterprise")
    make_enterprise.write(out, *make_enterprise.build(teams=3, team_size=12, projects=4, documents=8, seed=0))
    return out


@pytest.fixture
def settings(tmp_path, seed_dir):
    config = tmp_path / "data.json"
    admin = {"users": ["admin_01"]}
    config.write_text(json.dumps({"corax": {"config": {"jwt": JWT, "admin": admin}}}))
    return Settings(database=tmp_path / "app.db", seed_dir=seed_dir, corax_config=config,
                    demo_password=PASSWORD, password_iterations=1_000)  # fmt: skip


@pytest.fixture
def corax():
    return FakeCorax()


@pytest.fixture
def opa():
    return FakeOpa()


@pytest.fixture
def client(settings, corax, opa):
    with TestClient(create_app(settings, corax, opa)) as test_client:
        yield test_client


@pytest.fixture
def auth(client):
    """auth(username) -> the Authorization header of a signed-in user (via: another client)."""

    def headers(username: str, password: str = PASSWORD, via: TestClient | None = None) -> dict:
        answer = (via or client).post("/auth/login", json={"username": username, "password": password})
        assert answer.status_code == 200, answer.text
        return {"Authorization": f"Bearer {answer.json()['token']}"}

    return headers


@pytest.fixture
def jwt_settings():
    return JWT


@pytest.fixture
def password():
    return PASSWORD
