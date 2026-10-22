import pytest
from config import Settings
from fastapi.testclient import TestClient
from main import create_app


@pytest.fixture
def client(model_dir):
    with TestClient(create_app(Settings(model_dir=model_dir))) as client:
        yield client


def test_risk_for_normal_access(client, threshold):
    response = client.post("/risk", json={"user": "u1", "object": "r1"})

    assert response.status_code == 200
    body = response.json()
    assert body["risk"] < 0.1
    assert body["high_risk"] is False
    assert body["threshold"] == threshold
    assert body["reason"] is None


def test_risk_for_unusual_access(client):
    body = client.post("/risk", json={"user": "u1", "object": "r2"}).json()

    assert body["risk"] > 0.9
    assert body["high_risk"] is True


def test_unknown_user_returns_no_score(client, threshold):
    body = client.post("/risk", json={"user": "nobody", "object": "r1"}).json()

    assert body == {
        "risk": None,
        "high_risk": False,
        "threshold": threshold,
        "reason": "unknown user",
    }


@pytest.mark.parametrize(
    "payload",
    [{}, {"user": "u1"}, {"user": "", "object": "r1"}, {"user": "u1", "object": "x" * 257}],
)
def test_invalid_request_is_rejected(client, payload):
    assert client.post("/risk", json=payload).status_code == 422


def test_health_shows_model_info(client, threshold):
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["target_edge_type"] == ["user", "has_access", "resource"]
    assert body["risk_threshold"] == threshold
    assert body["users"] == 2
    assert body["objects"] == 2
