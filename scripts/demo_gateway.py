"""Both cases of the Corax architecture through the real gateway (deploy/docker-compose.yml).

Case 1, ordinary requests:  client -> Envoy -> OPA (rules; if they allow, ai-corax /risk)
                            -> the document store, or 403
Case 2, approved appeals:   admin -> Envoy -> OPA (is the caller an admin?) -> ai-corax /appeals
                            -> exact exception and candidate patterns -> the admin picks one
                            -> validated rule (a file) -> OPA reloads

The data is the synthetic enterprise of scripts/make_enterprise.py; demo.json names the requests
and the appeals. Acting as the admin, the script picks the pattern each scenario expects
(scenarios.json) and confirms it when its tier is large; the engineer's one-off appeal is rejected,
so only its exact exception applies.

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
sys.path[:0] = [str(REPO / "hgnn-job"), str(REPO / "ai-corax")]

import appeal_scenarios
import make_enterprise

OUT = REPO / "output" / "gateway"
CONFIG = json.loads((REPO / "deploy" / "corax-config.json").read_text(encoding="utf-8"))
JWT = CONFIG["corax"]["config"]["jwt"]


def prepare() -> None:
    from corax_hgnn.export import save, save_graph
    from corax_hgnn.graph import load_graph
    from corax_hgnn.train import TrainConfig, train

    data, hgnn = OUT / "data", OUT / "hgnn"
    built = make_enterprise.build(teams=2, team_size=12, projects=3, documents=8, seed=0)
    make_enterprise.write(data, *built)
    graph = load_graph(data, "accessed")
    # a small graph: the learning rate and patience used for the mini campus (scripts/README.md)
    config = TrainConfig(learning_rate=0.01, patience=50)
    result = train(graph, config)
    save(result, graph, config, hgnn, data_folder=data)
    save_graph(data, "accessed", hgnn)
    print(f"graph in {data}, HGNN in {hgnn} (val AUC {result.val_auc:.3f})")
    print("next: docker-compose -f deploy/docker-compose.yml up -d --build")


def token(user: str) -> str:
    """A signed JWT as the identity provider would issue it (demo secret of corax-config.json)."""

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
        return error.code, error.read().decode(errors="replace")


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
    """Submit the appeal as the admin, then pick the expected pattern (or reject a one-off)."""
    appeal_id = f"APL-{int(time.time())}-{appeal['scenario'].replace('_', '-')}"
    body = {"appeal_id": appeal_id, "user": appeal["user"], "object": appeal["document"]}
    status, state = call(gateway, "POST", "/appeals", admin, body)
    if status != 200:
        sys.exit(f"the appeal failed: {status} {state}")
    print(f"   {appeal['name']}: exception applied, {len(state['candidates'])} candidate patterns")
    if state["status"] != "awaiting_choice":
        print(f"      {state['status']}")
        return

    wanted = None if expected is None else {tuple(p.values()) for p in expected}
    chosen = next((c for c in state["candidates"]
                   if {tuple(p.values()) for p in c["predicates"]} == wanted), None)  # fmt: skip
    if chosen is None:
        status, state = call(gateway, "POST", f"/appeals/{appeal_id}/reject", admin)
        print(f"      rejected by the admin: {state['status']} (only the exception applies)")
        return
    path = f"/appeals/{appeal_id}/pick"
    status, state = call(gateway, "POST", path, admin, {"candidate": chosen["number"]})
    picked = state["picked"]
    print(f"      picked #{chosen['number']}: {picked['pattern']}")
    print(f"      tier {picked['tier']}: {picked['users']} users, {picked['pairs']} new pairs, "
          f"mean risk {picked['mean_risk']:.2f}")  # fmt: skip
    if state["status"] == "awaiting_confirmation":
        status, state = call(gateway, "POST", f"/appeals/{appeal_id}/confirm", admin)
        print(f"      confirmed by the admin ({'; '.join(picked['reasons'])})")
    checks = ", ".join(c["name"] for c in state.get("validation", []) if c["ok"])
    print(f"      {state['status']}" + (f" (validation: {checks})" if checks else ""))


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
    wait_until(lambda: read(None, reads[0]["document"]) == 403, "the gateway did not answer")

    print("\ncase 1: requests before the appeals")
    before = {s["name"]: read(s["user"], s["document"]) for s in reads}

    print("case 2: the appeals")
    first = demo["appeals"][0]
    body = {"appeal_id": "APL-not-admin", "user": first["user"], "object": first["document"]}
    status, _ = call(gateway, "POST", "/appeals", first["user"], body)
    print(f"   POST /appeals as {first['user']} (not an admin): {status}")
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
    print(f"\n200 = forwarded to the document store, 403 = denied at the gateway. risk = ai-corax "
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
