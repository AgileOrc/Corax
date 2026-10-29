"""The cases of scripts/prepare/make_office.py through the real gateway (deploy/docker-compose.yml).

    python scripts/demo_office.py prepare --seed 7   office graph, HGNN and labelled cases -> output/gateway
    docker-compose -f deploy/docker-compose.yml down -v   (a fresh stack: the app seeds its database once)
    docker-compose -f deploy/docker-compose.yml up -d --build
    python scripts/demo_office.py run                every case through Envoy at http://localhost:8080

prepare writes where the stack reads (output/gateway/data and output/gateway/hgnn), replacing the
enterprise of demo_gateway.py, and a demo.json for the console. run acts as the admin through the
gateway, as demo_gateway.py does: rejecting an appeal sends nothing to Corax; approving it creates the
appeal (the exact exception) and confirms the pattern the case expects; a large scope answers 409, and
the admin then acknowledges it (5c) or keeps only the exception (5d). Case 6 revokes 5a's rule by
deleting its file in the service's container (docker exec), as docs/demo.md 4.7 does by hand. The exit code
is 1 if a request did not answer as its case expects.
"""

import argparse
import json
import subprocess
import sys
import time

import demo_gateway
import make_office
from demo_gateway import OUT, call


def prepare(seed: int) -> None:
    from risk import RiskModel

    from hgnn.export import save, save_graph
    from hgnn.graph import load_graph
    from hgnn.train import TrainConfig, train

    data, hgnn = OUT / "data", OUT / "hgnn"
    nodes, edges, scenarios, cases = make_office.build(seed)
    make_office.write(data, nodes, edges, scenarios, cases)
    graph = load_graph(data, "accessed")
    config = TrainConfig(learning_rate=0.01, patience=50)  # a small graph, as demo_gateway.py trains it
    result = train(graph, config)
    save(result, graph, config, hgnn, data_folder=data)
    save_graph(data, "accessed", hgnn)

    problems = make_office.label(cases, *make_office.read_graph(data), RiskModel.load(hgnn))
    (data / "cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    (data / "demo.json").write_text(json.dumps(console(cases), indent=2), encoding="utf-8")
    structure, _ = make_office.read_graph(data)
    (data / "accounts.json").write_text(json.dumps(accounts(cases, structure), indent=2), encoding="utf-8")
    print(f"office of seed {seed} in {data}, HGNN in {hgnn} (val AUC {result.val_auc:.3f}, "
          f"threshold {cases['threshold']:.4f})")  # fmt: skip
    if problems:
        print("the cases do not hold with this model (try another seed):")
        for problem in problems:
            print(f"  {problem}")
        sys.exit(1)
    print("next: docker-compose -f deploy/docker-compose.yml down -v, then up -d --build")


def console(cases: dict) -> dict:
    """The console's buttons (demo/console): the requests and the appeals of the cases."""
    reads, appeals = [], []
    for c in cases["cases"]:
        if c["kind"] == "policy_denied":
            reads.append({"name": f"1: {c['title']}", "user": c["user"], "document": c["document"], "expect": 403})
        elif "admin" in c:
            reads.append({"name": f"{c['id']}: {c['user']} reads {c['document']}", "user": c["user"],
                          "document": c["document"], "expect": 403})  # fmt: skip
            appeals.append({"name": f"{c['id']}: {c['title']}", "user": c["user"], "document": c["document"],
                            "scenario": c["scenario"], "expect": c["expect"]["corax"]})  # fmt: skip
    return {"admin": cases["admin"], "reads": reads, "appeals": appeals}


def accounts(cases: dict, structure: dict) -> dict:
    """The accounts the web app's sign-in page offers (demo/web, served as assets/accounts.json):
    the people of the cases, by role and department only, so the page does not say what each of them
    will meet."""
    people = []
    for c in cases["cases"]:
        for user in (c.get("user"), (c.get("witness") or {}).get("user")):
            if user and user not in people:
                people.append(user)

    def label(user: str) -> str:
        role, department = structure[user]["holds"][0], structure[user]["works_in"][0]
        return f"{_short(role).replace('_', ' ').capitalize()}, {_short(department).title().replace('Hr', 'HR')}"

    listed = [{"username": _short(u).lower(), "label": label(u)} for u in people]
    return {"accounts": [*listed, {"username": cases["admin"], "label": "Corax admin"}]}


def _short(node: str) -> str:
    """'role_security_officer' -> 'security_officer', 'employee_E029' -> 'E029'."""
    return node.split("_", 1)[1]


class Run:
    def __init__(self, gateway: str, project: str):
        self.gateway, self.project = gateway, project
        self.rows: list[tuple[str, str, int, int]] = []

    def status(self, user: str, document: str, summary: bool = False) -> int:
        path = f"/documents/{document}" + ("/summary" if summary else "")
        return call(self.gateway, "GET", path, user)[0]

    def check(self, case: str, what: str, user: str, document: str, want: int, summary: bool = False,
              wait: float = 0) -> None:  # fmt: skip
        """One request; with wait, ask again until it answers want (OPA reloads a changed rule)."""
        deadline = time.time() + wait
        got = self.status(user, document, summary)
        while got != want and time.time() < deadline:
            time.sleep(0.25)
            got = self.status(user, document, summary)
        self.rows.append((case, what, want, got))
        print(f"   {'ok ' if got == want else 'BAD'} {what}: {got} (expected {want})")

    def appeal(self, admin: str, case: dict) -> str | None:
        """The admin's decision on the appeal of case; returns the appeal id when one was created."""
        if case["admin"]["appeal"] == "reject":
            print("   the admin rejects the appeal: nothing is sent to Corax")
            return None
        body = {"user": case["user"], "object": case["document"], "action": "read", "reason": case["title"]}
        status, record = call(self.gateway, "POST", "/corax/appeals", admin, body)
        if status != 201:
            sys.exit(f"the appeal failed: {status} {record}")
        print(f"   the admin approves: appeal {record['id']}, exception applied, "
              f"{len(record['candidates'])} candidate patterns")  # fmt: skip
        wanted = {tuple(p.values()) for p in case["expected"]}
        chosen = next((c for c in record["candidates"]
                       if {tuple(p.values()) for p in c["predicates"]} == wanted), None)  # fmt: skip
        if chosen is None:
            sys.exit(f"Corax did not offer the pattern of case {case['id']}: {case['expected']}")
        path = f"/corax/appeals/{record['id']}/confirm"
        print(f"   pattern #{chosen['index']}: {chosen['pattern']}")
        status, answer = call(self.gateway, "POST", path, admin, {"candidate": chosen["index"]})
        if status == 409 and isinstance(answer, dict) and "scope" in answer:
            scope = answer["scope"]
            print(f"   Corax asks again, tier {scope['tier']}: {scope['users']} users, {scope['pairs']} new pairs, "
                  f"mean risk {scope['mean_risk']:.2f} ({'; '.join(scope['reasons'])})")  # fmt: skip
            if case["admin"].get("large_scope") == "accept":
                print("   the admin accepts the scope (acknowledge_scope)")
                body = {"candidate": chosen["index"], "acknowledge_scope": True}
            else:
                print("   the admin declines the scope: only the exception stays")
                body = {"candidate": None}
            status, answer = call(self.gateway, "POST", path, admin, body)
        elif status == 200:
            scope = answer.get("chosen", {}).get("scope", {})
            print(f"   tier {scope.get('tier')}: {scope.get('users')} users, {scope.get('pairs')} new pairs, "
                  f"mean risk {scope.get('mean_risk', 0):.2f}: written at once")  # fmt: skip
        if status != 200:
            sys.exit(f"the confirmation failed: {status} {answer}")
        print(f"   Corax: {answer['status']}")
        return record["id"]

    def generated(self) -> list[str]:
        done = subprocess.run(["docker", "exec", f"{self.project}-service-1", "ls", "/runtime/generated"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")  # fmt: skip
        if done.returncode:
            sys.exit(f"docker exec {self.project}-service-1 failed: {done.stderr.strip()} (is --project right?)")
        return done.stdout.split()

    def revoke(self, appeal_id: str) -> None:
        name = f"{appeal_id}-rule.rego"
        container = f"{self.project}-service-1"
        done = subprocess.run(["docker", "exec", container, "rm", f"/runtime/generated/{name}"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")  # fmt: skip
        if done.returncode:
            sys.exit(f"docker exec {container} failed: {done.stderr.strip()} (is --project right?)")
        print(f"   deleted /runtime/generated/{name} in {container}")


def run(gateway: str, project: str) -> None:
    path = OUT / "data" / "cases.json"
    if not path.exists():
        sys.exit(f"{path} is missing: run prepare first")
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not cases["verified"]:
        sys.exit("the cases are not verified with the trained model: run prepare again (another seed)")
    admin, by_id = cases["admin"], {c["id"]: c for c in cases["cases"]}
    r = Run(gateway, project)
    left = r.generated()
    if left:
        sys.exit(f"the stack still holds the files of earlier appeals ({', '.join(left)}): the cases need a fresh "
                 "one (docker-compose -f deploy/docker-compose.yml down -v, then up -d)")  # fmt: skip

    print(f"waiting for the gateway at {gateway} ...")
    usual = by_id["2"]
    demo_gateway.wait_until(lambda: r.status(usual["user"], usual["document"], True) == 200,
                            "the gateway does not allow case 2; see docker-compose logs opa")  # fmt: skip
    print(f"threshold {cases['threshold']:.4f}\n")

    for case in cases["cases"]:
        print(f"case {case['id']} ({case['kind']}): {case['title']}")
        if case["kind"] == "policy_denied":
            r.check("1", "read", case["user"], case["document"], case["expect"]["status"])
        elif case["kind"] in ("ai_allowed", "ai_denied"):
            r.check(case["id"], f"summary, risk {case['risk']:.4f}", case["user"], case["document"],
                    case["expect"]["status"], summary=True)  # fmt: skip
        elif case["kind"] == "revoke":
            r.revoke(by_id[case["revokes"]]["appeal_id"])
            w, a = case["expect"]["witness"], case["expect"]["appellant"]
            r.check("6", "colleague after the revoke", w["user"], w["document"], w["after"], wait=10)
            r.check("6", "appellant after the revoke (exception)", a["user"], a["document"], a["after"])
        else:
            witness = case.get("witness")
            r.check(case["id"], "appellant before", case["user"], case["document"], case["expect"]["before"])
            if witness:
                r.check(case["id"], "colleague before", witness["user"], witness["document"], witness["before"])
            case["appeal_id"] = r.appeal(admin, case)
            r.check(case["id"], "appellant after", case["user"], case["document"], case["expect"]["after"],
                    wait=10)  # fmt: skip
            if witness:
                # a 403 that stays 403 is seen only after OPA had time to load whatever was written
                time.sleep(0 if witness["after"] == 200 else 1)
                r.check(case["id"], "colleague after", witness["user"], witness["document"], witness["after"],
                        wait=10)  # fmt: skip
                if witness.get("why"):
                    print(f"       {witness['why']}")
        print()

    bad = [row for row in r.rows if row[2] != row[3]]
    print(f"{len(r.rows) - len(bad)} of {len(r.rows)} requests answered as expected "
          "(200 = forwarded to the document store, 403 = denied at the gateway)")  # fmt: skip
    for case, what, want, got in bad:
        print(f"  case {case}, {what}: {got}, expected {want}")
    sys.exit(1 if bad else 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["prepare", "run"])
    parser.add_argument("--seed", type=int, default=0, help="prepare: which office")
    parser.add_argument("--gateway", default="http://localhost:8080")
    parser.add_argument("--project", default="corax", help="run: compose project of the stack (for the revoke)")
    args = parser.parse_args()
    if args.step == "prepare":
        prepare(args.seed)
    else:
        run(args.gateway, args.project)


if __name__ == "__main__":
    main()
