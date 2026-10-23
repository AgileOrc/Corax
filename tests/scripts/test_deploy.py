import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import jwt
import pytest
from make_token import make_token

ROOT = Path(__file__).parents[2]
DEPLOY = ROOT / "deploy"
DEMO_CONFIG = DEPLOY / "demo" / "data.json"


@pytest.fixture
def opa():
    for found in (os.environ.get("OPA_PATH"), shutil.which("opa"), ROOT.parent / "opa.exe"):
        if found and Path(found).exists():
            return str(found)
    pytest.skip("opa not found (set OPA_PATH)")


def test_token_is_accepted_with_the_demo_config():
    settings = json.loads(DEMO_CONFIG.read_text(encoding="utf-8"))["corax"]["config"]["jwt"]

    claims = jwt.decode(
        make_token(DEMO_CONFIG, "lecturer_P1_0", 5), settings["secret"], algorithms=["HS256"],
        issuer=settings["iss"], audience=settings["aud"],
    )

    assert claims["sub"] == "lecturer_P1_0"
    assert 0 < claims["exp"] - claims["iat"] <= 300


def test_no_token_without_a_secret(tmp_path):
    config = tmp_path / "data.json"
    config.write_text(json.dumps({"corax": {"config": {"jwt": {"cert": "-----BEGIN PUBLIC KEY-----"}}}}), encoding="utf-8")

    with pytest.raises(ValueError, match="no jwt.secret"):
        make_token(config, "alice", 5)


def test_demo_policy_tests_pass(opa):
    completed = subprocess.run(
        [opa, "test", str(ROOT / "policy" / "request.rego"), str(ROOT / "policy" / "authz.rego"), str(DEPLOY / "demo")],
        capture_output=True, text=True, check=False,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_compose_mounts_files_that_exist():
    compose = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")
    mounted = re.findall(r"- (\.\.?/[^:${}]+):", compose)

    assert mounted
    for path in mounted:
        assert (DEPLOY / path).exists(), path
    assert (ROOT / (re.search(r"dockerfile: (\S+)", compose).group(1))).exists()


def test_envoy_routes_admin_api_to_the_service_and_denies_without_opa():
    envoy = (DEPLOY / "envoy.yaml").read_text(encoding="utf-8")

    assert "failure_mode_allow: false" in envoy
    assert re.search(r'prefix: "/corax/"\}\s*\n\s*route: \{cluster: service\}', envoy)


def test_opa_loads_only_the_framework_not_its_example_config():
    compose = (DEPLOY / "docker-compose.yml").read_text(encoding="utf-8")

    assert "config.example.json" not in compose
    assert "../policy:" not in compose
