"""The document app's demo through the gateway, written as a log (deploy/README.md).

    python scripts/demo_backend.py                    # the stack of deploy/docker-compose.yml on :8080
    python scripts/demo_backend.py --gateway http://localhost:8180
    docker compose -f deploy/docker-compose.yml run --rm demo   # the same in a container

57 cases in seven parts, the way people use the app (login, documents, access requests, an admin who
decides). Each case is checked against what it should show; the summary at the end lists them all.
  1  the policy decides (Rego): what the current rules allow and deny, BOLA attempts
  2  identity and routes: missing, forged and expired tokens, unknown routes, admin-only routes
  3  the AI check: every employee may read every summary (a route that is deliberately too broad),
     so the policy allows all of them and Corax's AI decides: a usual pair passes, an unusual one
     is denied
  4  access requests whose best rule is small: the admin approves and picks the pattern; it reaches
     few people, so it applies with no second confirmation; a colleague in the same situation, who
     never asked, can read too
  5  access requests whose best rule is large: they wait for the admin, who declines (only the exact
     exception stays) or reviews the scope and approves
  6  after the decisions: exceptions skip the AI check, rules do not; pending, repeated, rejected
     and already readable requests; the appeal's history
  7  revoking rules and an exception by deleting their files

Run it on a fresh stack (it adds exceptions and rules): docker-compose -f deploy/docker-compose.yml
down -v, then up -d. OPA's reason and the AI risk of each request come from Envoy's access log, the
reload time from OPA's log and the generated Rego from the service's runtime folder, through the docker
CLI; the compose project is found from the container that publishes the gateway's port. The exit
code is 1 when a case did not show what it should.
"""

import argparse
import base64
import csv
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "service"))

from risk import RiskModel
from tier import TierLimits

PREPARED = REPO / "output" / "gateway"  # what "demo_gateway.py prepare" writes: data/ and hgnn/
CONFIG = REPO / "demo" / "data.json"
PASSWORD_ENV = "CORAX_DEMO_PASSWORD"
STATUS = {200: "OK", 201: "Created", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 409: "Conflict",
          422: "Unprocessable Entity"}  # fmt: skip
BROAD = ("shared", "works_in", "owned_by")  # "user.works_in = object.owned_by": the whole department
# the reads of demo.json that part 1 sends, in this order
POLICY_READS = [
    "Project member reads a document of their project",
    "Analyst reads a public document of their department outside their projects",
    "Analyst reads an internal document of their department outside their projects",
    "Employee reads a document of another department's project they work on",
    "Sales analyst reads a confidential Finance document (BOLA)",
    "Engineer reads a confidential HR document (BOLA)",
    "Finance analyst reads a confidential Finance document outside their projects",
    "Analyst reads a document of another department stored at their own site",
]
SMALL = ["coordinator", "manager", "data_steward", "quality_lead"]
LARGE = ["one_off", "one_off_hr", "facility_manager", "hr_partner", "security_officer", "auditor"]


class Stack:
    """The running stack: HTTP through the gateway, logs and files through docker."""

    def __init__(self, gateway: str, password: str, project: str | None = None):
        self.gateway, self.password = gateway.rstrip("/"), password
        self.project = project or _own_project() or _project_publishing(urlparse(self.gateway).port or 80)
        _sync_clock()
        self.tokens: dict[str, str] = {}
        self.traces = 0

    def container(self, service: str) -> str:
        return f"{self.project}-{service}-1"

    def token(self, user: str) -> str:
        if user not in self.tokens:
            status, body, _ = self.call("POST", "/auth/login", None, {"username": user, "password": self.password})
            if status != 200:
                sys.exit(f"login as {user} failed: {status} {body}")
            self.tokens[user] = body["token"]
        return self.tokens[user]

    def call(self, method: str, path: str, user: str | None, body: dict | None = None,
             bearer: str | None = None) -> tuple[int, dict, dict]:  # fmt: skip
        """The status, the JSON answer, and Envoy's log of the request (reason, risk). The request is
        sent with the user's token, or with bearer instead (a token made by hand), or with none."""
        self.traces += 1
        trace = f"demo-{int(time.time())}-{self.traces}"
        headers = {"Content-Type": "application/json", "x-demo-trace": trace}
        if bearer or user:
            headers["Authorization"] = f"Bearer {bearer or self.token(user)}"
        data = json.dumps(body).encode() if body is not None else None
        since = _now(-2)  # the trace finds the line; the margin covers the clocks of Windows and WSL
        try:
            with urllib.request.urlopen(urllib.request.Request(self.gateway + path, data, headers, method=method),
                                        timeout=60) as response:  # fmt: skip
                status, text = response.status, response.read().decode()
        except urllib.error.HTTPError as error:
            status, text = error.code, error.read().decode(errors="replace")
        try:
            answer = json.loads(text) if text else {}
        except ValueError:
            answer = {"text": text}
        return status, answer, self.envoy_log(trace, since) if path != "/auth/login" else {}

    def envoy_log(self, trace: str, since: str, seconds: float = 10) -> dict:
        deadline = time.time() + seconds
        while time.time() < deadline:
            for line in _docker("logs", "--since", since, self.container("envoy")).splitlines():
                if line.rstrip().endswith(f"trace={trace}"):
                    return envoy_fields(line)
            time.sleep(0.1)
        return {}

    def opa_reload_ms(self, since: str, seconds: float = 5) -> float | None:
        """The longest file-watch reload OPA logged since then, in milliseconds."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            durations = [json.loads(line)["duration"] for line in _docker("logs", "--since", since, self.container("opa")).splitlines()
                         if '"Processed file watch event."' in line]  # fmt: skip
            if durations:
                time.sleep(0.3)  # one write is several file events
                durations = [json.loads(line)["duration"] for line in _docker("logs", "--since", since, self.container("opa")).splitlines()
                             if '"Processed file watch event."' in line]  # fmt: skip
                return max(durations) / 1e6
            time.sleep(0.1)
        return None

    def generated(self) -> list[str]:
        return _docker("exec", self.container("service"), "ls", "/runtime/generated").split()

    def read_generated(self, name: str) -> str:
        return _docker("exec", self.container("service"), "cat", f"/runtime/generated/{name}")

    def delete_generated(self, name: str) -> None:
        _docker("exec", self.container("service"), "rm", f"/runtime/generated/{name}")


_DOCKER: list[str] = []


def _docker_command() -> list[str]:
    """docker, or on Windows without it "wsl docker" (Docker installed inside WSL only)."""
    if not _DOCKER:
        if shutil.which("docker"):
            _DOCKER.append("docker")
        elif os.name == "nt" and shutil.which("wsl"):
            _DOCKER.extend(["wsl", "docker"])
        else:
            sys.exit("demo_backend.py needs the docker command, to read Envoy's and OPA's logs. Run it where docker "
                     "works, or in a container: docker compose -f deploy/docker-compose.yml run --rm demo")
    return _DOCKER


def _docker(*args: str) -> str:
    result = subprocess.run([*_docker_command(), *args], capture_output=True, text=True, encoding="utf-8", check=False)
    # through wsl, stderr also has wsl's own warnings (Windows paths it cannot translate)
    stderr = "".join(line for line in result.stderr.splitlines(keepends=True) if not line.startswith("wsl: "))
    if result.returncode != 0:
        sys.exit(f"docker {' '.join(args[:2])} failed: {stderr.strip()}")
    # docker logs writes the container's stderr (OPA's log) on stderr; the other commands only stdout
    return result.stdout + stderr if args[0] == "logs" else result.stdout


def _own_project() -> str | None:
    """The compose project of this container, when the script runs as the "demo" service."""
    if not Path("/.dockerenv").exists() or "HOSTNAME" not in os.environ:
        return None
    label = '{{index .Config.Labels "com.docker.compose.project"}}'
    result = subprocess.run([*_docker_command(), "inspect", "-f", label, os.environ["HOSTNAME"]], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _project_publishing(port: int) -> str:
    """The compose project whose Envoy publishes the gateway's port, when the script runs on the host."""
    names = _docker("ps", "--filter", f"publish={port}", "--format", "{{.Names}}").split()
    envoy = next((n for n in names if n.endswith("-envoy-1")), None)
    if envoy is None:
        sys.exit(f"no running envoy container publishes port {port}; start the stack first")
    return envoy.removesuffix("-envoy-1")


def envoy_fields(line: str) -> dict:
    """reason and risk of an access log line of deploy/envoy.yaml (None where Envoy wrote "-")."""
    found = dict(re.findall(r"(reason|risk)=(.*?)(?= risk=| trace=)", line))
    return {key: None if value in ("-", "") else value for key, value in found.items()}


_CLOCK = [0.0]  # seconds the Docker host's clock is ahead of this one (Windows and WSL can differ)


def _sync_clock() -> None:
    reported = _docker("info", "--format", "{{.SystemTime}}").strip()
    # RFC 3339 with nanoseconds; datetime reads at most microseconds
    _CLOCK[0] = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", reported)).timestamp() - time.time()


def _now(shift: float = 0) -> str:
    """The current time on the Docker host's clock (plus shift seconds), for docker logs --since."""
    moment = time.time() + _CLOCK[0] + shift
    return datetime.fromtimestamp(moment, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_token(sub: str, jwt: dict, secret: str | None = None, lifetime: int = 600) -> str:
    """A JWT made by hand with the claims Envoy and OPA check: the demo's secret unless another is
    given (a forgery), valid for lifetime seconds (negative: already expired)."""

    def part(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    claims = {"sub": sub, "iss": jwt["iss"], "aud": jwt["aud"], "exp": int(time.time()) + lifetime}
    signed = f"{part(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())}.{part(json.dumps(claims).encode())}"
    signature = hmac.new((secret or jwt["secret"]).encode(), signed.encode(), hashlib.sha256).digest()
    return f"{signed}.{part(signature)}"


class Graph:
    """Facts of the enterprise graph and the access history, to pick the users and documents."""

    def __init__(self, folder: Path):
        with (folder / "nodes.csv").open(newline="", encoding="utf-8") as f:
            self.types = {row["id"]: row["type"] for row in csv.DictReader(f)}
        self.facts: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        self.access: set[tuple[str, str]] = set()
        with (folder / "edges.csv").open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row["relation"] == "accessed":
                    self.access.add((row["src"], row["dst"]))
                else:
                    self.facts[row["src"]][row["relation"]].add(row["dst"])
        self.employees = sorted(n for n, t in self.types.items() if t == "employee")
        self.documents = sorted(n for n, t in self.types.items() if t == "document")

    def holds(self, predicate: dict, user: str, document: str) -> bool:
        kind, relation, other = predicate["kind"], predicate["relation"], predicate["other"]
        if kind == "shared":
            return bool(self.facts[user][relation] & self.facts[document][other])
        if kind == "user_has":
            return other in self.facts[user][relation]
        if kind == "object_has":
            return other in self.facts[document][relation]
        return document == other  # object identity

    def opened(self, predicates: list[dict], skip: set[str]) -> list[tuple[str, str]]:
        """The pairs a pattern opens that the history does not have, without the users in skip."""
        return [(u, d) for u in self.employees if u not in skip for d in self.documents
                if (u, d) not in self.access and all(self.holds(p, u, d) for p in predicates)]  # fmt: skip


# --- the log ------------------------------------------------------------------


def show_request(method: str, path: str, who: str | None, status: int, log: dict, threshold: float) -> list[str]:
    lines = [f"  request : {method} {path}" + (f" as {who}" if who else ""),
             f"  response: {status} {STATUS.get(status, '')}".rstrip()]  # fmt: skip
    if log.get("risk"):
        lines.append(f"  threshold = {threshold:.3f}, risk = {float(log['risk']):.4f}")
    lines.append(f"  reason  : {log.get('reason') or '-'}")
    return lines


def one_line(method: str, path: str, user: str, status: int, log: dict) -> str:
    detail = log.get("reason") or STATUS.get(status, "")
    if log.get("risk"):
        detail += f", risk {float(log['risk']):.4f}"
    return f"{method} {path} as {user} -> {status} ({detail})"


def indicators(scope: dict, limits: TierLimits) -> list[str]:
    rows = [("share of users", f"{scope['user_share']:.0%}", f"{limits.max_user_share:.0%}", scope["user_share"] > limits.max_user_share),
            ("new pairs", str(scope["pairs"]), str(limits.max_pairs), scope["pairs"] > limits.max_pairs)]  # fmt: skip
    if scope.get("mean_risk") is not None:
        rows.append(("mean risk", f"{scope['mean_risk']:.2f}", f"{limits.max_mean_risk:.2f}",
                     scope["mean_risk"] > limits.max_mean_risk))  # fmt: skip
    lines = [f"  {'indicators':<19}{'value':>8}{'limit':>8}"]
    lines += [f"    {name:<17}{value:>8}{limit:>8}    {'over' if over else 'ok'}" for name, value, limit, over in rows]
    return lines


def rule_body(rego: str) -> list[str]:
    """The allow rule of a generated file, without its package line and metadata."""
    start = rego.index("allow if")
    return [f"              {line.replace(chr(9), '  ')}" for line in rego[start:].strip().splitlines()]


def predicates(candidate: dict) -> set[tuple]:
    return {(p["kind"], p["relation"], p["other"]) for p in candidate["predicates"]}


def pick(candidates: list[dict], wanted: set[tuple] | None) -> dict:
    """The candidate with exactly the wanted predicates; without them (None), a department-wide
    one: "user.works_in = object.owned_by" alone, else with "user works_in <department>", else the
    candidate that opens the most users."""
    if wanted is not None:
        exact = next((c for c in candidates if predicates(c) == wanted), None)
        if exact:
            return exact

    def rank(c: dict) -> tuple:
        mine = predicates(c)
        return (mine == {BROAD}, BROAD in mine and any(p[:2] == ("user_has", "works_in") for p in mine),
                BROAD in mine, c["users"] or 0)  # fmt: skip

    return max(candidates, key=rank)


def summary(results: list[tuple[int, str, str, bool]]) -> list[str]:
    failed = [r for r in results if not r[3]]
    lines = [f"Summary: {len(results)} cases, {len(results) - len(failed)} as expected"
             + (f", {len(failed)} not: {', '.join(str(r[0]) for r in failed)}" if failed else "")]  # fmt: skip
    lines += [f"  {case:>3}  {'ok  ' if ok else 'FAIL'}  {title}: {got}" for case, title, got, ok in results]
    return lines


# --- the cases ----------------------------------------------------------------


class Demo:
    def __init__(self, stack: Stack, graph: Graph, model: RiskModel, demo: dict, scenarios: dict):
        self.stack, self.graph, self.model, self.demo = stack, graph, model, demo
        self.reads = {r["name"]: r for r in demo["reads"]}
        self.appeals = {a["scenario"]: a for a in demo["appeals"]}
        self.expected = {name: None if s["expected"] is None else {tuple(p.values()) for p in s["expected"]}
                         for name, s in scenarios.items()}  # fmt: skip
        self.admin = demo["admin"]
        self.jwt = json.loads(CONFIG.read_text(encoding="utf-8"))["corax"]["config"]["jwt"]
        self.limits = TierLimits(max_user_share=0.06)  # AUTO_APPLY_MAX_USER_SHARE in deploy/docker-compose.yml
        self.parts = self.case = 0
        self.title = ""
        self.results: list[tuple[int, str, str, bool]] = []
        self.opened: set[tuple[str, str]] = set()  # pairs this run's exceptions and rules opened
        self.records: dict[str, dict] = {}  # scenario -> what its appeal did

    # -- helpers

    def part(self, title: str) -> None:
        self.parts += 1
        print(f"\n\nPart {self.parts}: {title}")

    def header(self, title: str) -> None:
        self.case += 1
        self.title = title
        print(f"\nCase {self.case}: {title}")

    def check(self, ok: bool, got: str, expected: str) -> None:
        self.results.append((self.case, self.title, got, ok))
        if not ok:
            print(f"  check   : NOT AS EXPECTED, should be {expected}")

    def request(self, method: str, path: str, user: str | None, body: dict | None = None, bearer: str | None = None,
                who: str | None = None) -> tuple[int, dict, dict]:  # fmt: skip
        status, answer, log = self.stack.call(method, path, user, body, bearer)
        print("\n".join(show_request(method, path, who or user, status, log, self.model.threshold)))
        return status, answer, log

    def risk(self, user: str, document: str) -> float:
        return self.model.risk(user, document).risk or 0.0

    def get(self, path: str, user: str) -> tuple[int, dict, dict]:
        return self.stack.call("GET", path, user)

    def after(self, user: str, document: str, label: str = "after   ") -> tuple[int, dict]:
        time.sleep(0.3)
        status, _, log = self.get(f"/documents/{document}", user)
        print(f"  {label}: {one_line('GET', f'/documents/{document}', user, status, log)}")
        return status, log

    def revoke(self, title: str, name: str, witness: tuple[str, str] | None, want: int = 403) -> None:
        self.header(title)
        since = _now()
        self.stack.delete_generated(name)
        reload = self.stack.opa_reload_ms(since)
        print(f"  policy  : - {name} (deleted)")
        print(f"  opa     : reloaded in {reload:.0f} ms (no restart)" if reload else "  opa     : no reload seen")
        if witness is None:
            self.check(False, "nobody to read", f"{want} for the pair the file opened")
            return
        status, log = self.after(*witness)
        self.check(status == want, f"{status} ({log.get('reason')})", f"{want}")

    # -- part 1

    def policy(self) -> None:
        self.part("the policy decides (Rego): what the current rules allow and deny, BOLA attempts")
        for name in POLICY_READS:
            r = self.reads[name]
            self.header(name)
            status, _, log = self.request("GET", f"/documents/{r['document']}", r["user"])
            self.check(status == r["expect"], f"{status} ({log.get('reason')})", str(r["expect"]))

    # -- part 2

    def identity(self) -> None:
        self.part("identity and routes: who is calling, and which routes exist")
        member = self.reads[POLICY_READS[0]]
        user, document = member["user"], member["document"]
        path = f"/documents/{document}"
        cases = [
            ("A request without a token", "GET", path, None, None, "(no token)", "missing or invalid token"),
            ("A token that claims to be the admin, signed with another key", "GET", "/admin/access-requests",
             None, make_token(self.admin, self.jwt, secret="not-the-demo-secret"), f"(forged token of {self.admin})",
             "missing or invalid token"),
            ("An expired token", "GET", path, None, make_token(user, self.jwt, lifetime=-3600),
             f"(expired token of {user})", "missing or invalid token"),
            ("A valid token of someone the enterprise does not know", "GET", path, None,
             make_token("employee_E999", self.jwt), "employee_E999", "denied by policy"),
            ("A route the application does not have: DELETE a document", "DELETE", path, user, None, None,
             "no matching route"),
            ("The admin reads a document (admins decide on access, they are not employees)", "GET", path,
             self.admin, None, None, "denied by policy"),
            ("An employee opens the admin's queue of access requests", "GET", "/admin/access-requests", user,
             None, None, "denied by policy"),
            ("An employee calls Corax's appeal API directly", "POST", "/corax/appeals", user, None, None,
             "admin only"),
        ]  # fmt: skip
        for title, method, route, caller, bearer, who, reason in cases:
            self.header(title)
            body = {"user": user, "object": document, "action": "read"} if route == "/corax/appeals" else None
            status, _, log = self.request(method, route, caller, body, bearer, who)
            self.check(status == 403 and log.get("reason") == reason, f"{status} ({log.get('reason')})",
                       f"403 ({reason})")  # fmt: skip

        self.header("A login with a wrong password")
        username = user.split("_", 1)[1].lower()
        status, answer, _ = self.stack.call("POST", "/auth/login", None, {"username": username, "password": "wrong"})
        print(f'  request : POST /auth/login {{"username": "{username}", "password": "wrong"}}')
        print(f"  response: {status} {STATUS.get(status, '')}, {answer.get('detail')}")
        self.check(status == 401, str(status), "401")

        analyst = self.reads["Sales analyst reads a confidential Finance document (BOLA)"]
        self.header("An employee approves their own access request")
        status, request, _ = self.stack.call("POST", f"/access-requests/{analyst['document']}", analyst["user"],
                                             {"reason": "I need the Finance numbers"})  # fmt: skip
        print(f"  request : POST /access-requests/{analyst['document']} as {analyst['user']} -> {status} "
              f"{STATUS.get(status, '')}, request #{request.get('id')} {request.get('status')}")  # fmt: skip
        print("  status  : waits for the admin")
        self.pending = request.get("id")
        status, _, log = self.request("POST", f"/admin/access-requests/{self.pending}/approve", analyst["user"])
        self.check(status == 403 and request.get("status") == "pending",
                   f"{status} ({log.get('reason')}), the request {request.get('status')}",
                   "403 (denied by policy), the request pending")  # fmt: skip

    # -- part 3

    def ai_check(self) -> None:
        self.part("the AI check: every employee may read every summary, so the AI decides")
        for reader in self.demo["summaries"]:
            user = reader["user"]
            usual = min((d for d in self.graph.documents if (user, d) in self.graph.access),
                        key=lambda d: self.risk(user, d))  # fmt: skip
            unusual = max((d for d in self.graph.documents if (user, d) not in self.graph.access),
                          key=lambda d: self.risk(user, d))  # fmt: skip
            for document, like, want, reason in ((usual, "like", 200, "allowed"),
                                                 (unusual, "unlike anything in", 403, "high AI risk")):  # fmt: skip
                self.header(f"{reader['name']} reads the summary of {document}, {like} their access history")
                status, _, log = self.request("GET", f"/documents/{document}/summary", user)
                self.check(status == want and log.get("reason") == reason, f"{status} ({log.get('reason')})",
                           f"{want} ({reason})")  # fmt: skip

    # -- parts 4 and 5

    def appeal(self, entry: dict, decide: str, wanted: set[tuple] | None = None) -> dict:
        """An access request through the app. It waits for the admin, whose approval starts the
        appeal (the exact exception at once). The admin then keeps only the exception ("decline"),
        picks a pattern that reaches few people, applied with no second confirmation ("small"), or
        picks a pattern and confirms its large scope ("accept")."""
        user, document = entry["user"], entry["document"]
        self.header(f"{entry['name']} ({user}, {document})")
        record = {"user": user, "document": document, "status": None, "second": False, "large": False}
        lines = [f"  expect  : {entry['expect']}"]
        witness = tuple(entry["witness"]) if entry.get("witness") and decide != "accept" else None
        if witness:  # known in advance: measured before anything is approved
            status, _, log = self.get(f"/documents/{witness[1]}", witness[0])
            record["before"] = status
            lines += [f"  witness : {witness[0]} ({entry['witness_name']}) never asks for access",
                      f"  before  : {one_line('GET', f'/documents/{witness[1]}', witness[0], status, log)}"]  # fmt: skip
        since = _now()
        status, request, _ = self.stack.call("POST", f"/access-requests/{document}", user, {"reason": entry["name"]})
        if status != 201:
            print("\n".join(lines + [f"  request : POST /access-requests/{document} as {user} -> {status} {request}"]))
            return record
        rid = record["request"] = request["id"]
        lines.append(f"  request : POST /access-requests/{document} as {user} -> {status} {STATUS[status]}, "
                     f"request #{rid} {request['status']}")  # fmt: skip
        lines.append("  status  : waits for the admin")
        final = {}
        since = _now()
        status, answer, _ = self.stack.call("POST", f"/admin/access-requests/{rid}/approve", self.admin)
        appeal = answer.get("appeal", {})
        lines.append(f"  request : POST /admin/access-requests/{rid}/approve as {self.admin} -> {status} "
                     f"{STATUS.get(status, '')}, {answer.get('request', {}).get('status')}")  # fmt: skip
        if status != 200 or not appeal.get("candidates"):
            print("\n".join(lines + [f"  corax   : {appeal}"]))
            return record
        record["appeal"] = appeal["id"]
        candidates = appeal["candidates"]
        lines.append(f"  corax   : POST /corax/appeals -> 201 Created, {appeal['id']}, exception written")
        chosen = candidates[0]
        record["large"] = (chosen.get("scope") or {}).get("tier") == "large"

        if decide == "small":
            small = [c for c in candidates if (c.get("scope") or {}).get("tier") == "small"]
            chosen = next((c for c in small if predicates(c) == wanted), small[0] if small else candidates[0])
            body = {"candidate": chosen["index"]}
            lines.append(f"  admin   : picks candidate #{chosen['index']}: {chosen.get('description') or chosen['pattern']}")
            since = _now()
            status, answer, _ = self.stack.call("POST", f"/admin/access-requests/{rid}/confirm", self.admin, body)
            final = answer.get("appeal", {})
            record["second"] = status == 409
            lines += [f"  request : POST /admin/access-requests/{rid}/confirm {json.dumps(body)}",
                      f"  response: {status} {STATUS.get(status, '')}, {final.get('status')}"]  # fmt: skip
            if final.get("status") == "rule_applied":
                lines += indicators(final["chosen"]["scope"], self.limits)
                lines.append("  tier    : SMALL -> applied with no second confirmation")
        elif decide == "decline":
            lines.append("  admin   : declines the generalisation, keeps only the exception")
            status, answer, _ = self.stack.call("POST", f"/admin/access-requests/{rid}/confirm", self.admin, {"candidate": None})
            lines += [f'  request : POST /admin/access-requests/{rid}/confirm {{"candidate": null}}',
                      f"  response: {status} {STATUS.get(status, '')}, {answer.get('appeal', {}).get('status')}"]  # fmt: skip
            final = answer.get("appeal", {})
        elif not final and decide == "accept":
            chosen = pick(candidates, wanted)
            # someone else the rule opens, whom the AI would let pass, denied now; the colleague of
            # demo.json first
            opened = self.graph.opened(chosen["predicates"], skip={user})
            colleague = entry["witness"][0] if entry.get("witness") else None
            usual = sorted((p for p in opened if p not in self.opened and self.risk(*p) <= self.model.threshold),
                           key=lambda p: (p[0] != colleague, self.risk(*p)))  # fmt: skip
            for pair in usual[:10]:
                status, _, log = self.get(f"/documents/{pair[1]}", pair[0])
                if status == 403:
                    witness, record["before"] = pair, status
                    lines.insert(1, f"  before  : {one_line('GET', f'/documents/{pair[1]}', pair[0], status, log)}")
                    break
            body = {"candidate": chosen["index"]}
            if chosen["index"] == 1 and record["large"]:  # its large scope is already on the screen
                body["acknowledge_scope"] = True
                lines.append("  admin   : confirms the large scope of #1 after reviewing it")
            else:
                lines.append(f"  admin   : picks candidate #{chosen['index']}: {chosen['pattern']}")
                status, answer, _ = self.stack.call("POST", f"/admin/access-requests/{rid}/confirm", self.admin, body)
                lines.append(f"  request : POST /admin/access-requests/{rid}/confirm {json.dumps(body)}")
                if status == 409 and "scope" in answer.get("appeal", {}):
                    lines += ["  response: 409 Conflict, needs admin confirmation",
                              *indicators(answer["appeal"]["scope"], self.limits),
                              "  admin   : approves after reviewing the scope"]  # fmt: skip
                    body["acknowledge_scope"] = True
            if body.get("acknowledge_scope"):
                since = _now()
                status, answer, _ = self.stack.call("POST", f"/admin/access-requests/{rid}/confirm", self.admin, body)
                lines.append(f"  request : POST /admin/access-requests/{rid}/confirm {json.dumps(body)}")
            final = answer.get("appeal", {})
            lines.append(f"  response: {status} {STATUS.get(status, '')}, {final.get('status')}")

        record["status"], record["witness"] = final.get("status"), witness
        self.opened.add((user, document))
        if final.get("status") == "rule_applied":
            self.opened |= set(self.graph.opened(chosen["predicates"], skip=set()))
            name = f"{final['id']}-rule.rego"
            lines += [f"  policy  : + {name}", *rule_body(self.stack.read_generated(name))]
            reload = self.stack.opa_reload_ms(since)
            lines.append(f"  opa     : reloaded in {reload:.0f} ms (no restart)" if reload else "  opa     : no reload seen")
            record["rule"], record["predicates"] = name, chosen["predicates"]
        elif final.get("status") == "exception_only":
            lines.append(f"  policy  : + {final['id']}-exception.rego (only {user} -> {document})")
        print("\n".join(lines))
        if witness:
            record["after"], _ = self.after(*witness)
        return record

    def small_rules(self) -> None:
        self.part("access requests whose best rule is small: the admin picks it, no second confirmation")
        for scenario in SMALL:
            record = self.records[scenario] = self.appeal(self.appeals[scenario], "small", self.expected[scenario])
            ok = record["status"] == "rule_applied" and not record["second"]
            self.check(ok and record.get("before") == 403 and record.get("after") == 200,
                       f"{record['status']}, {'a second confirmation' if record['second'] else 'one confirmation'}, "
                       f"colleague {record.get('before')} -> {record.get('after')}",
                       "rule_applied with one confirmation, colleague 403 -> 200")  # fmt: skip

    def large_rules(self) -> None:
        self.part("access requests whose best rule is large: they wait for the admin, who decides")
        for scenario in LARGE:
            entry = self.appeals[scenario]
            record = self.records[scenario] = self.appeal(entry, entry["admin"], self.expected[scenario])
            if entry["admin"] == "decline":
                status, _ = self.after(entry["user"], entry["document"], "appeal  ")
                record["own"] = status
                if record.get("witness") is None:  # another document the declined rule would have opened
                    other = next((d for d in self.graph.documents if d != entry["document"]
                                  and (entry["user"], d) not in self.graph.access | self.opened
                                  and self.graph.facts[d]["owned_by"] & self.graph.facts[entry["user"]]["works_in"]),
                                 None)  # fmt: skip
                    if other:
                        record["after"], _ = self.after(entry["user"], other, "other   ")
                ok = record["large"] and record["status"] == "exception_only" and status == 200 and record.get("after") == 403
                self.check(ok, f"{'large' if record['large'] else 'small'}, {record['status']}, appellant {status}, "
                               f"another pair {record.get('after')}",
                           "large, exception_only, appellant 200, another pair 403")  # fmt: skip
            else:
                ok = record["large"] and record["status"] == "rule_applied" and (
                    record.get("witness") is None or (record.get("before"), record.get("after")) == (403, 200))
                self.check(ok, f"{'large' if record['large'] else 'small'}, {record['status']}, someone else "
                               f"{record.get('before')} -> {record.get('after')}",
                           "large, rule_applied, someone else 403 -> 200")  # fmt: skip

        # an analyst of Sales asks for a Sales document; the admin picks a department-wide pattern
        sales = self.appeals["manager"]
        bola = self.reads["Sales analyst reads a confidential Finance document (BOLA)"]["user"]
        appellant = next(e for e in self.graph.employees if e not in (sales["user"], bola)
                         and self.graph.facts[e]["works_in"] == self.graph.facts[sales["user"]]["works_in"]
                         and "role_analyst" in self.graph.facts[e]["holds"])  # fmt: skip
        document = next(d for d in self.graph.documents if (appellant, d) not in self.graph.access
                        and (appellant, d) not in self.opened
                        and self.graph.facts[d]["owned_by"] & self.graph.facts[appellant]["works_in"])  # fmt: skip
        entry = {"name": "Sales analyst asks for a Sales document", "user": appellant, "document": document,
                 "expect": "the best pattern is large; the admin picks a department-wide one and confirms its scope"}  # fmt: skip
        record = self.records["department"] = self.appeal(entry, "accept")
        self.check(record["large"] and record["status"] == "rule_applied"
                   and (record.get("before"), record.get("after")) == (403, 200),
                   f"{'large' if record['large'] else 'small'}, {record['status']}, someone else "
                   f"{record.get('before')} -> {record.get('after')}",
                   "large, rule_applied, someone else 403 -> 200")  # fmt: skip

    # -- part 6

    def after_decisions(self) -> None:
        self.part("after the decisions")
        auditor = self.records["auditor"]
        self.header("An exception skips the AI check: the auditor reads the document they asked for")
        status, _, log = self.request("GET", f"/documents/{auditor['document']}", auditor["user"])
        print(f"  ai      : not asked; the model's risk of this pair is {self.risk(auditor['user'], auditor['document']):.3f}")
        self.check(status == 200 and log.get("reason") == "allowed by appeal exception",
                   f"{status} ({log.get('reason')})", "200 (allowed by appeal exception)")  # fmt: skip

        self.header("A rule does not skip the AI check: an unusual pair the auditor rule opens")
        rule = next((self.records[s] for s in ("auditor", "security_officer") if self.records[s].get("rule")), None)
        pairs = [] if rule is None else [
            p for p in self.graph.opened(rule["predicates"], skip=set())
            if p != (rule["user"], rule["document"]) and self.risk(*p) > self.model.threshold
        ]  # fmt: skip
        if pairs:
            user, document = max(pairs, key=lambda p: self.risk(*p))
            print(f"  policy  : {rule['rule']} allows {user} -> {document}")
            status, _, log = self.request("GET", f"/documents/{document}", user)
            self.check(status == 403 and log.get("reason") == "high AI risk", f"{status} ({log.get('reason')})",
                       "403 (high AI risk)")  # fmt: skip
        else:
            print("  (no pair of the applied rules has a risk above the threshold)")
            self.check(False, "no such pair", "403 (high AI risk)")

        coordinator = self.records["coordinator"]
        self.header("A colleague outside the rule stays denied: an engineer reads the coordinator's document")
        department = self.graph.facts[coordinator["user"]]["works_in"]
        engineer = next(e for e in self.graph.employees if self.graph.facts[e]["works_in"] == department
                        and "role_engineer" in self.graph.facts[e]["holds"]
                        and (e, coordinator["document"]) not in self.graph.access
                        and (e, coordinator["document"]) not in self.opened)  # fmt: skip
        status, _, log = self.request("GET", f"/documents/{coordinator['document']}", engineer)
        self.check(status == 403 and log.get("reason") == "denied by policy", f"{status} ({log.get('reason')})",
                   "403 (denied by policy)")  # fmt: skip

        officer = self.records["security_officer"]
        self.header(f"The admin reads the history of an appeal ({officer.get('appeal')})")
        status, answer, log = self.request("GET", f"/corax/appeals/{officer.get('appeal')}", self.admin)
        for event in answer.get("history", []):
            print(f"  history : {event['at']}  {event['event']:<18} by {event['by']}")
        if answer.get("chosen"):
            print(f"  rule    : {answer['chosen']['pattern']} ({answer['chosen']['scope']['tier']})")
        events = [e["event"] for e in answer.get("history", [])]
        self.check(status == 200 and events == ["created", "exception_applied", "rule_applied"],
                   f"{status}, {' -> '.join(events)}", "200, created -> exception_applied -> rule_applied")  # fmt: skip

        analyst = self.reads["Sales analyst reads a confidential Finance document (BOLA)"]
        self.header("An employee asks again while their request is still pending")
        status, answer, _ = self.request("POST", f"/access-requests/{analyst['document']}", analyst["user"],
                                         {"reason": "Still need it"})  # fmt: skip
        print(f"  detail  : {answer.get('detail')}")
        self.check(status == 409, str(status), "409")

        self.header("The admin approves a request that is already decided")
        status, answer, _ = self.request("POST", f"/admin/access-requests/{coordinator.get('request')}/approve", self.admin)
        print(f"  detail  : {answer.get('detail')}")
        self.check(status == 409, str(status), "409")

        member = self.reads[POLICY_READS[0]]
        self.header("An employee asks for a document they can read already: the admin's approval finds it")
        status, request, _ = self.stack.call("POST", f"/access-requests/{member['document']}", member["user"],
                                             {"reason": "Just to be sure"})  # fmt: skip
        print(f"  request : POST /access-requests/{member['document']} as {member['user']} -> {status} "
              f"{STATUS.get(status, '')}, request #{request.get('id')} {request.get('status')}")  # fmt: skip
        approved, answer, _ = self.stack.call("POST", f"/admin/access-requests/{request.get('id')}/approve", self.admin)
        state = answer.get("request", {}).get("status")
        print(f"  request : POST /admin/access-requests/{request.get('id')}/approve as {self.admin} -> {approved} "
              f"{STATUS.get(approved, '')}, {state}")  # fmt: skip
        print(f"  note    : {answer.get('request', {}).get('note')}")
        self.check(status == 201 and state == "already_granted", f"{status}, {state}", "201, already_granted")

        self.header("The admin rejects a request with a note")
        note = "Finance documents are for Finance; ask your manager for the figures you need"
        status, answer, _ = self.stack.call("POST", f"/admin/access-requests/{self.pending}/reject", self.admin, {"note": note})
        state = answer.get("status") or answer.get("request", {}).get("status")
        print(f'  request : POST /admin/access-requests/{self.pending}/reject {{"note": "{note}"}} as {self.admin} '
              f"-> {status} {STATUS.get(status, '')}, {state}")  # fmt: skip
        read, _ = self.after(analyst["user"], analyst["document"])
        self.check(status == 200 and state == "rejected" and read == 403, f"{status}, {state}, read {read}",
                   "200, rejected, read 403")  # fmt: skip

        self.header("The employee sees the decisions on their requests")
        status, answer, _ = self.request("GET", "/access-requests", analyst["user"])
        mine = answer.get("requests", [])
        for r in mine:
            print(f"  request : #{r['id']} {r['document_id']}: {r['status']}" + (f", note: {r['note']}" if r.get("note") else ""))
        self.check(status == 200 and any(r["status"] == "rejected" and r.get("note") == note for r in mine),
                   f"{status}, {len(mine)} request(s)", "200, the rejection with its note")  # fmt: skip

        self.header("Only employees ask for access: the admin asks for a document")
        status, _, log = self.request("POST", f"/access-requests/{member['document']}", self.admin, {"reason": "test"})
        self.check(status == 403, f"{status} ({log.get('reason')})", "403 (denied by policy)")

        self.header("The admin's queue: every request of this run and its state")
        status, answer, _ = self.request("GET", "/admin/access-requests", self.admin)
        counts = Counter(r["status"] for r in answer.get("requests", []))
        print("  states  : " + ", ".join(f"{state} {n}" for state, n in sorted(counts.items())))
        self.check(status == 200 and counts.get("pending", 0) == 0, f"{status}, {sum(counts.values())} requests",
                   "200, none pending")  # fmt: skip

    # -- part 7

    def revokes(self) -> None:
        self.part("revoking: delete the file, OPA reloads, access is gone")
        for scenario, label in (("department", "the department-wide rule of the Sales analyst"),
                                ("security_officer", "the security officer rule"),
                                ("coordinator", "the coordinator rule"),
                                ("manager", "the manager rule")):  # fmt: skip
            record = self.records[scenario]
            if record.get("rule"):
                self.revoke(f"Revoke {label} ({record['rule']})", record["rule"], record.get("witness"))
            else:
                self.header(f"Revoke {label}")
                self.check(False, "no rule was applied", "403 after deleting the rule")
        auditor = self.records["auditor"]
        name = f"{auditor.get('appeal')}-exception.rego"
        # the auditor rule still allows the pair, so the AI check now decides it
        self.revoke(f"Revoke the auditor's exception ({name})", name, (auditor["user"], auditor["document"]))

    def run(self) -> int:
        existing = self.stack.generated()
        print(f"Corax demo through the document app at {self.stack.gateway} (stack {self.stack.project}), "
              f"risk threshold {self.model.threshold:.3f}")  # fmt: skip
        if existing:
            print(f"note: the stack has {len(existing)} generated file(s) already; on a fresh stack "
                  "(down -v, then up -d) the cases show what they describe")  # fmt: skip
        self.policy()
        self.identity()
        self.ai_check()
        self.small_rules()
        self.large_rules()
        self.after_decisions()
        self.revokes()
        print("\n\n" + "\n".join(summary(self.results)))
        return 0 if all(ok for *_, ok in self.results) else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="The document app's demo through the gateway, as a log.")
    parser.add_argument("--gateway", default="http://localhost:8080")
    parser.add_argument("--project", help="compose project of the stack (default: found from docker)")
    parser.add_argument("--prepared", type=Path, default=PREPARED,
                        help="the graph and the HGNN the stack runs with (default: output/gateway)")  # fmt: skip
    args = parser.parse_args()
    stack = Stack(args.gateway, os.environ.get(PASSWORD_ENV, "123456"), args.project)
    data = args.prepared / "data"
    demo = json.loads((data / "demo.json").read_text(encoding="utf-8"))
    scenarios = {s["name"]: s for s in json.loads((data / "scenarios.json").read_text(encoding="utf-8"))["scenarios"]}
    sys.exit(Demo(stack, Graph(data), RiskModel.load(args.prepared / "hgnn"), demo, scenarios).run())


if __name__ == "__main__":
    main()
