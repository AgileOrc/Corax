"""The Rego of the framework and of the demo application, with OPA (skipped when opa is missing):
`opa check --strict`, `opa test`, and the demo configuration of deploy/ evaluated on Envoy input."""

import base64
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
OPA = next(
    (p for p in (os.environ.get("OPA_PATH"), shutil.which("opa")) if p and Path(p).exists()), None
)
POLICIES = [str(REPO / "policy"), str(REPO / "deploy" / "demo-app" / "policy")]
CONFIG = REPO / "deploy" / "corax-config.json"

pytestmark = pytest.mark.skipif(not OPA, reason="opa not found (set OPA_PATH)")


def opa(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([OPA, *args], capture_output=True, text=True, timeout=120)


def test_policies_pass_the_strict_check():
    run = opa("check", "--strict", *POLICIES)
    assert run.returncode == 0, run.stdout + run.stderr


def test_policy_tests_pass():
    run = opa("test", *POLICIES)
    assert run.returncode == 0, run.stdout + run.stderr


def token(sub: str, jwt: dict) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    claims = {"sub": sub, "iss": jwt["iss"], "aud": jwt["aud"], "exp": int(time.time()) + 600}
    signed = f"{part({'alg': 'HS256', 'typ': 'JWT'})}.{part(claims)}"
    signature = hmac.new(jwt["secret"].encode(), signed.encode(), hashlib.sha256).digest()
    return f"{signed}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


@pytest.mark.parametrize(
    ("user", "method", "path", "allowed", "reason"),
    [
        ("admin_01", "POST", "/corax/appeals", True, "admin action"),
        ("admin_01", "GET", "/corax/appeals/appeal-0001", True, "admin action"),
        ("admin_01", "POST", "/corax/appeals/appeal-0001/confirm", True, "admin action"),
        ("employee_E001", "POST", "/corax/appeals", False, "admin only"),
        ("employee_E001", "POST", "/corax/appeals/appeal-0001/confirm", False, "admin only"),
        ("employee_E001", "GET", "/documents/document_D001", True, "allowed without AI check"),
        ("employee_E001", "GET", "/documents/document_D002", False, "denied by policy"),
        ("employee_E001", "DELETE", "/documents/document_D001", False, "no matching route"),
    ],
)
def test_demo_configuration(tmp_path, user, method, path, allowed, reason):
    jwt = json.loads(CONFIG.read_text(encoding="utf-8"))["corax"]["config"]["jwt"]
    graph = {
        "employee_E001": {"works_on": ["project_sales1"]},
        "document_D001": {"belongs_to": ["project_sales1"]},
        "document_D002": {"belongs_to": ["project_finance1"]},
    }
    (tmp_path / "graph.json").write_text(json.dumps({"corax": {"graph": graph}}))
    http = {"method": method, "path": path, "headers": {"authorization": f"Bearer {token(user, jwt)}"}}
    (tmp_path / "input.json").write_text(json.dumps({"attributes": {"request": {"http": http}}}))

    # as OPA loads them in deploy/docker-compose.yml (policy/config.example.json is not loaded);
    # ai-corax is not running: the AI check fails open, as documented
    data = [REPO / "policy" / "corax", REPO / "deploy" / "demo-app" / "policy", CONFIG,
            tmp_path / "graph.json"]  # fmt: skip
    run = opa(
        "eval", "--format", "json", "--input", str(tmp_path / "input.json"),
        *(f"--data={p}" for p in data),
        "data.corax.authz.result",
    )  # fmt: skip
    assert run.returncode == 0, run.stderr
    result = json.loads(run.stdout)["result"][0]["expressions"][0]["value"]
    assert result["allowed"] is allowed
    assert result["dynamic_metadata"]["corax_reason"] == reason
