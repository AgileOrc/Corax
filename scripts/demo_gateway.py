"""Both cases of the Corax architecture through the real gateway (deploy/docker-compose.yml).

Case 1, ordinary requests:  client -> Envoy -> OPA (rules; if they allow, the service's /risk)
                            -> the document store, or 403
Case 2, approved appeals:   admin -> Envoy -> OPA (is the caller an admin?) -> the service
                            /corax/appeals (checks the admin's JWT again) -> exact exception and
                            candidate patterns -> the admin confirms one -> validated rule (a
                            file) -> OPA reloads

The data is the synthetic enterprise of scripts/prepare/make_enterprise.py; demo.json names the requests
and the appeals. Acting as the admin, the script confirms the pattern each scenario expects
(scenarios.json), acknowledging the scope when the rule is large (a small rule is written at
once); for the engineer's one-off appeal it confirms no pattern, so only the exact exception applies.

    python scripts/demo_gateway.py prepare    enterprise graph and HGNN -> output/gateway
    docker-compose -f deploy/docker-compose.yml up -d --build
    python scripts/demo_gateway.py run        requests through Envoy at http://localhost:8080
    docker-compose -f deploy/docker-compose.yml down -v
"""

import argparse
import base64
import hashlib
import hmac
import json
import sys
import time
import urllib.error
import urllib.request
import warnings
from pathlib import Path

warnings.filterwarnings("ignore", message="`torch.jit.script` is deprecated")
REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "service"), str(REPO / "scripts" / "prepare")]

import appeal_scenarios
import make_enterprise

OUT = REPO / "output" / "gateway"
CONFIG = json.loads((REPO / "demo" / "data.json").read_text(encoding="utf-8"))
JWT = CONFIG["corax"]["config"]["jwt"]


def prepare() -> None:
    from hgnn.export import save, save_graph
    from hgnn.graph import load_graph
    from hgnn.train import TrainConfig, train

    data, hgnn = OUT / "data", OUT / "hgnn"
    built = make_enterprise.build(teams=3, team_size=12, projects=4, documents=8, seed=0)
    make_enterprise.write(data, *built)
    # the web app's sign-in page then lists its own accounts, those of this enterprise (demo/web)
    (data / "accounts.json").write_text(json.dumps({"accounts": []}), encoding="utf-8")
    graph = load_graph(data, "accessed")
    # a small graph: the learning rate and patience used for the mini campus (scripts/README.md)
    config = TrainConfig(learning_rate=0.01, patience=50)
    result = train(graph, config)
    save(result, graph, config, hgnn, data_folder=data)
    save_graph(data, "accessed", hgnn)
    print(f"graph in {data}, HGNN in {hgnn} (val AUC {result.val_auc:.3f})")
    print("next: docker-compose -f deploy/docker-compose.yml up -d --build")


def token(user: str) -> str:
    """A signed JWT as the identity provider would issue it (demo secret of demo/data.json)."""

    def part(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    claims = {"sub": user, "iss": JWT["iss"], "aud": JWT["aud"], "exp": int(time.time()) + 600}
    head = part(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = part(json.dumps(claims).encode())
    signature = hmac.new(JWT["secret"].encode(), f"{head}.{body}".encode(), hashlib.sha256)
    return f"{head}.{body}.{part(signature.digest())}"


def call(gateway: str, method: str, path: str, user: str | None, body: dict | None = None):
    """(HTTP status, answer) of one request through the gateway."""
    headers = {"Content-Type": "application/json"}
    if user:
        headers["Authorization"] = f"Bearer {token(user)}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(gateway + path, data, headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        text = error.read().decode(errors="replace")
        try:
            return error.code, json.loads(text)
        except ValueError:
            return error.code, text


def wait_until(condition, message: str, seconds: float = 60.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if condition():
                return
        except OSError:
            pass
        time.sleep(0.5)
    sys.exit(message)


def handle_appeal(gateway: str, admin: str, appeal: dict, expected) -> None:
    """Create the appeal as the admin, then confirm the expected pattern (or keep only the
    exception for a one-off). A large scope is confirmed again with acknowledge_scope."""
    body = {"user": appeal["user"], "object": appeal["document"], "action": "read",
            "reason": appeal["name"]}  # fmt: skip
    status, record = call(gateway, "POST", "/corax/appeals", admin, body)
    if status != 201:
        sys.exit(f"the appeal failed: {status} {record}")
    path = f"/corax/appeals/{record['id']}/confirm"
    print(f"   {appeal['name']}: {record['id']}, exception applied, "
          f"{len(record['candidates'])} candidate patterns")  # fmt: skip

    wanted = None if expected is None else {tuple(p.values()) for p in expected}
    chosen = next((c for c in record["candidates"]
                   if {tuple(p.values()) for p in c["predicates"]} == wanted), None)  # fmt: skip
    if chosen is None:
        status, record = call(gateway, "POST", path, admin, {"candidate": None})
        print(f"      no pattern confirmed: {record['status']}")
        return
    print(f"      picked #{chosen['index']}: {chosen['pattern']}")
    status, answer = call(gateway, "POST", path, admin, {"candidate": chosen["index"]})
    if status == 409 and isinstance(answer, dict) and "scope" in answer:
        scope = answer["scope"]
        print(f"      tier {scope['tier']}: {scope['users']} users, {scope['pairs']} new pairs, "
              f"mean risk {scope['mean_risk']:.2f} ({'; '.join(scope['reasons'])})")  # fmt: skip
        status, answer = call(gateway, "POST", path, admin,
                              {"candidate": chosen["index"], "acknowledge_scope": True})  # fmt: skip
        print("      confirmed again with acknowledge_scope")
    if status != 200:
        sys.exit(f"the confirmation failed: {status} {answer}")
    scope = answer.get("chosen", {}).get("scope", {})
    if scope.get("tier") == "small":
        print(f"      tier small: {scope['users']} users, {scope['pairs']} new pairs, "
              f"mean risk {scope['mean_risk']:.2f}: written at once, no acknowledge_scope")  # fmt: skip
    checks = ", ".join(c["name"] for c in answer.get("validation", []) if c["ok"])
    print(f"      {answer['status']}" + (f" (validation: {checks})" if checks else ""))


def run(gateway: str) -> None:
    from risk import RiskModel

    model = RiskModel.load(OUT / "hgnn")
    demo = json.loads((OUT / "data" / "demo.json").read_text(encoding="utf-8"))
    scenarios = appeal_scenarios.load(OUT / "data" / "scenarios.json")
    expected = {s.name: s.expected for s in scenarios.scenarios}
    admin, reads = demo["admin"], demo["reads"]

    def read(user: str | None, document: str) -> int:
        return call(gateway, "GET", f"/documents/{document}", user)[0]

    print(f"waiting for the gateway at {gateway} ...")
    # an allowed request, so a gateway that denies everything (OPA down) is not mistaken for ready
    first = reads[0]
    wait_until(lambda: read(first["user"], first["document"]) == 200,
               "the gateway does not allow a permitted request; see docker-compose logs opa")  # fmt: skip

    print("\ncase 1: requests before the appeals")
    before = {s["name"]: read(s["user"], s["document"]) for s in reads}

    print("case 2: the appeals")
    appeal = demo["appeals"][0]
    body = {"user": appeal["user"], "object": appeal["document"], "action": "read"}
    status, _ = call(gateway, "POST", "/corax/appeals", appeal["user"], body)
    print(f"   POST /corax/appeals as {appeal['user']} (not an admin): {status}")
    for appeal in demo["appeals"]:
        handle_appeal(gateway, admin, appeal, expected[appeal["scenario"]])
        user, document = appeal["user"], appeal["document"]
        wait_until(lambda u=user, d=document: read(u, d) == 200, "OPA did not load the exception", 30)
    time.sleep(2)  # OPA reloads the last generated rule

    after = {s["name"]: read(s["user"], s["document"]) for s in reads}
    rows = [["", "risk", "before appeals", "after appeals"]]
    for s in reads:
        risk = model.risk(s["user"], s["document"]).risk
        rows.append([s["name"], f"{risk:.3f}", str(before[s["name"]]), str(after[s["name"]])])
    widths = [max(len(row[i]) for row in rows) + 2 for i in range(len(rows[0]))]
    print()
    for row in rows:
        print("".join(cell.ljust(width) for cell, width in zip(row, widths, strict=True)).rstrip())
    print(f"\n200 = forwarded to the document store, 403 = denied at the gateway. risk = the service's "
          f"score; OPA denies a request its rules allow when risk > {model.threshold:.3f} "
          "(approved exceptions are not checked).")  # fmt: skip
    print("try it by hand in the console: http://localhost:8090 (or CORAX_CONSOLE_PORT)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["prepare", "run"])
    parser.add_argument("--gateway", default="http://localhost:8080")
    args = parser.parse_args()
    if args.step == "prepare":
        prepare()
    else:
        run(args.gateway)


if __name__ == "__main__":
    main()
