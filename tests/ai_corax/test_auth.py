import base64
import hashlib
import hmac
import json
import os
import time

import jwt
import pytest
from auth import AdminAuth, AuthError

SECRET = "test-secret-with-enough-length-for-hs256"
CLAIMS = {"sub": "admin_rina", "iss": "test-issuer", "aud": "test-api"}


def write_config(path, jwt_settings, admins=("admin_rina",)):
    config = {"corax": {"config": {"jwt": jwt_settings, "admin": {"users": list(admins)}}}}
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


@pytest.fixture
def config_file(tmp_path):
    return write_config(
        tmp_path / "data.json", {"secret": SECRET, "iss": "test-issuer", "aud": "test-api"}
    )


def token(claims=None, key=SECRET, algorithm="HS256", lifetime=300):
    payload = {**CLAIMS, "exp": int(time.time()) + lifetime, **(claims or {})}
    return jwt.encode(payload, key, algorithm=algorithm)


def bearer(value):
    return f"Bearer {value}"


def status_of(auth, authorization):
    with pytest.raises(AuthError) as error:
        auth.authenticate(authorization)
    return error.value.status


def test_valid_admin_token_returns_the_admin(config_file):
    assert AdminAuth(config_file).authenticate(bearer(token())) == "admin_rina"


@pytest.mark.parametrize(
    "authorization",
    [
        None,
        "",
        "Basic YWRtaW46YWRtaW4=",
        bearer("not-a-jwt"),
        bearer(token(key="another-secret-with-enough-length-x")),
        bearer(token(lifetime=-60)),
        bearer(token({"iss": "evil"})),
        bearer(token({"aud": "other-api"})),
        bearer(jwt.encode({**CLAIMS, "exp": int(time.time()) + 300}, None, algorithm="none")),
        bearer(jwt.encode(CLAIMS, SECRET, algorithm="HS256")),
        bearer(jwt.encode({k: v for k, v in CLAIMS.items() if k != "sub"} | {"exp": int(time.time()) + 300}, SECRET, algorithm="HS256")),
    ],
    ids=["missing", "empty", "basic", "garbage", "wrong-key", "expired", "wrong-iss", "wrong-aud", "alg-none", "no-exp", "no-sub"],
)
def test_invalid_tokens_are_401(config_file, authorization):
    assert status_of(AdminAuth(config_file), authorization) == 401


def test_valid_token_of_a_non_admin_is_403(config_file):
    assert status_of(AdminAuth(config_file), bearer(token({"sub": "bob"}))) == 403


def test_not_configured_is_503(tmp_path):
    assert status_of(AdminAuth(None), bearer(token())) == 503
    assert status_of(AdminAuth(tmp_path / "missing.json"), bearer(token())) == 503


def test_config_without_jwt_is_503(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(json.dumps({"corax": {"config": {"admin": {"users": ["admin_rina"]}}}}), encoding="utf-8")

    assert status_of(AdminAuth(path), bearer(token())) == 503


def test_config_without_admins_lets_nobody_in(tmp_path):
    path = write_config(tmp_path / "data.json", {"secret": SECRET, "iss": "test-issuer", "aud": "test-api"}, admins=())

    assert status_of(AdminAuth(path), bearer(token())) == 403


def test_admin_list_changes_are_picked_up(config_file):
    auth = AdminAuth(config_file)
    assert status_of(auth, bearer(token({"sub": "bob"}))) == 403

    write_config(config_file, {"secret": SECRET, "iss": "test-issuer", "aud": "test-api"}, admins=("bob",))
    later = time.time_ns() + 1_000_000_000
    os.utime(config_file, ns=(later, later))

    assert auth.authenticate(bearer(token({"sub": "bob"}))) == "bob"
    assert status_of(auth, bearer(token())) == 403


@pytest.fixture
def rsa_keys():
    pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return private, public.decode()


def test_rs256_with_a_public_key(tmp_path, rsa_keys):
    private, public = rsa_keys
    path = write_config(tmp_path / "data.json", {"cert": public, "iss": "test-issuer", "aud": "test-api"})

    assert AdminAuth(path).authenticate(bearer(token(key=private, algorithm="RS256"))) == "admin_rina"


def b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def test_public_key_cannot_be_used_as_an_hmac_secret(tmp_path, rsa_keys):
    _, public = rsa_keys
    path = write_config(tmp_path / "data.json", {"cert": public, "iss": "test-issuer", "aud": "test-api"})
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps({**CLAIMS, "exp": int(time.time()) + 300}).encode())
    signature = b64(hmac.new(public.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest())

    assert status_of(AdminAuth(path), bearer(f"{header}.{body}.{signature}")) == 401
