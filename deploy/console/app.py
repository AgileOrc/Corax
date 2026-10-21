"""Demo console: a web page to try Corax by hand (deploy/README.md).

It plays the identity provider of the demo: you pick who you are, it issues a signed JWT for that
user, and it sends your request through the real gateway (Envoy -> OPA -> app or ai-corax), so
what you see is what the gateway decided. To show *why*, it also asks OPA for the decision of the
same request (reason, AI risk, which package allowed it); that is read-only and inside the Docker
network.

Not part of Corax itself: in production the identity provider and the clients are your own.
"""

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

GATEWAY = os.environ.get("GATEWAY", "http://envoy:8080")
OPA = os.environ.get("OPA", "http://opa:8181")
AI_CORAX = os.environ.get("AI_CORAX", "http://ai-corax:8000")
GENERATED = Path(os.environ.get("GENERATED", "/runtime/generated"))
STATE = Path(os.environ.get("STATE", "/state"))
CONFIG = json.loads(Path(os.environ.get("CONFIG", "/config/corax-config.json")).read_text())
DEMO = Path(os.environ.get("DEMO", "/config/demo.json"))
SETTINGS = CONFIG["corax"]["config"]
HERE = Path(__file__).resolve().parent

app = FastAPI(title="Corax demo console")


class ReadRequest(BaseModel):
    user: str  # who you are, e.g. "employee_E001"
    document: str  # e.g. "document_D016"


class AppealRequest(BaseModel):
    admin: str  # who sends the appeal (only admins pass the gateway)
    user: str  # the employee who was denied
    document: str


class AppealStep(BaseModel):
    admin: str
    appeal_id: str
    candidate: int | None = None


def token(user: str) -> str:
    def part(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    jwt = SETTINGS["jwt"]
    claims = {"sub": user, "exp": int(time.time()) + 600}
    claims.update({key: jwt[key] for key in ("iss", "aud") if key in jwt})
    head = part(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = part(json.dumps(claims).encode())
    signature = hmac.new(jwt["secret"].encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{part(signature)}"


def http(method: str, url: str, body: dict | None = None, bearer: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data, headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode()
            return {"status": response.status, "body": json.loads(text) if text else None}
    except urllib.error.HTTPError as error:
        text = error.read().decode(errors="replace")
        try:
            return {"status": error.code, "body": json.loads(text)}
        except ValueError:
            return {"status": error.code, "body": text or None}


def opa(path: str, input_: dict):
    """The value of data.<path> for this input (None when undefined)."""
    answer = http("POST", f"{OPA}/v1/data/{path}", {"input": input_})
    return answer["body"].get("result") if isinstance(answer["body"], dict) else None


def explain(user: str, document: str, bearer: str) -> dict:
    """OPA's decision for the same request, and which package allowed it (read-only)."""
    http_request = {"method": "GET", "path": f"/documents/{document}",
                    "headers": {"authorization": f"Bearer {bearer}"}}  # fmt: skip
    result = opa("corax/authz/result", {"attributes": {"request": {"http": http_request}}}) or {}
    request = {"user": {"id": user}, "action": "read",
               "resource": {"type": "document", "id": document}}  # fmt: skip
    packages = [("application", "app/authz/allow"), ("generated", "app/generated/allow"),
                ("exception", "app/exceptions/allow")]  # fmt: skip
    metadata = result.get("dynamic_metadata", {})
    return {
        "reason": metadata.get("corax_reason"),
        "risk": metadata.get("corax_risk"),
        "granted_by": [name for name, path in packages if opa(path, request) is True],
    }


@app.get("/")
def page() -> FileResponse:
    return FileResponse(HERE / "index.html")


@app.get("/api/demo")
def demo() -> dict:
    """Named requests and appeals written by scripts/make_enterprise.py."""
    return json.loads(DEMO.read_text()) if DEMO.exists() else {"reads": [], "appeals": []}


@app.get("/api/people")
def people() -> dict:
    """Who you can be (admins and the graph's employees) and the documents, with their relations."""
    answer = http("GET", f"{OPA}/v1/data/corax/graph")
    graph = answer["body"].get("result", {}) if isinstance(answer["body"], dict) else {}
    health = http("GET", f"{AI_CORAX}/health")["body"] or {}
    return {
        "admins": SETTINGS.get("admins", []),
        "graph": {n: r for n, r in graph.items() if n.startswith(("employee_", "document_"))},
        "risk_threshold": health.get("risk_threshold") if isinstance(health, dict) else None,
    }


@app.post("/api/read")
def read(request: ReadRequest) -> dict:
    bearer = token(request.user)
    answer = http("GET", f"{GATEWAY}/documents/{request.document}", bearer=bearer)
    return {**answer, "decision": explain(request.user, request.document, bearer)}


@app.post("/api/appeals")
def appeal(request: AppealRequest) -> dict:
    body = {
        "appeal_id": f"APL-{int(time.time() * 1000) % 10**8:08d}",
        "user": request.user,
        "object": request.document,
        "action": "read",
    }
    return http("POST", f"{GATEWAY}/appeals", body, bearer=token(request.admin))


@app.post("/api/appeals/{step}")
def appeal_step(step: str, request: AppealStep) -> dict:
    if step not in ("pick", "confirm", "reject"):
        return {"status": 404, "body": {"detail": f"unknown step {step!r}"}}
    body = {"candidate": request.candidate} if step == "pick" else None
    path = f"{GATEWAY}/appeals/{request.appeal_id}/{step}"
    return http("POST", path, body, bearer=token(request.admin))


@app.get("/api/policy")
def policy() -> dict:
    """What OPA enforces on top of the application rules, and ai-corax's audit log."""
    files = sorted(GENERATED.glob("*.rego")) if GENERATED.exists() else []
    rules = [{"file": path.name, "rego": path.read_text()} for path in files]
    audit = STATE / "audit.jsonl"
    log = [json.loads(line) for line in audit.read_text().splitlines()[-40:]] if audit.exists() else []
    return {
        "exceptions": [r for r in rules if r["file"].endswith("-exception.rego")],
        "rules": [r for r in rules if r["file"].endswith("-rule.rego")],
        "log": list(reversed(log)),
    }
