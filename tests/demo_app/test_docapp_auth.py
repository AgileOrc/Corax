import time

import jwt
import pytest


@pytest.mark.parametrize("username", ["e001", "E001", "employee_E001"])
def test_login_by_username_or_id(client, username):
    answer = client.post("/auth/login", json={"username": username, "password": "123456"})

    assert answer.status_code == 200
    body = answer.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 3600
    assert body["user"]["id"] == "employee_E001" and "password" not in body["user"]


def test_token_is_what_opa_and_the_service_verify(client, jwt_settings):
    token = client.post("/auth/login", json={"username": "e001", "password": "123456"}).json()["token"]

    claims = jwt.decode(token, jwt_settings["secret"], algorithms=["HS256"], audience=jwt_settings["aud"], issuer=jwt_settings["iss"])
    assert claims["sub"] == "employee_E001"
    assert claims["exp"] - claims["iat"] == 3600


@pytest.mark.parametrize(("username", "password"), [("e001", "wrong"), ("nobody", "123456"), ("", "x")])
def test_wrong_credentials(client, username, password):
    answer = client.post("/auth/login", json={"username": username, "password": password})

    assert answer.status_code in (401, 422)
    assert "token" not in answer.text


def test_me(client, auth):
    me = client.get("/me", headers=auth("e001")).json()

    assert me["kind"] == "employee" and me["role"] == "manager" and me["department"] == "sales"
    assert len([p for p in me["projects"] if p.startswith("sales")]) == 2
    assert client.get("/me", headers=auth("admin_01")).json()["kind"] == "admin"


def test_me_needs_a_valid_token(client, jwt_settings):
    def claims(**changes):
        now = int(time.time())
        return {"sub": "employee_E001", "iss": jwt_settings["iss"], "aud": jwt_settings["aud"], "iat": now, "exp": now + 60, **changes}

    forged = jwt.encode(claims(), "another-secret-that-corax-does-not-know", algorithm="HS256")
    expired = jwt.encode(claims(exp=int(time.time()) - 10), jwt_settings["secret"], algorithm="HS256")
    wrong_audience = jwt.encode(claims(aud="elsewhere"), jwt_settings["secret"], algorithm="HS256")
    unknown_user = jwt.encode(claims(sub="employee_E999"), jwt_settings["secret"], algorithm="HS256")

    assert client.get("/me").status_code == 401
    for token in (forged, expired, wrong_audience, unknown_user, "not-a-token"):
        assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
