"""Write a random office graph and the cases that take a request down every path through Corax.

    python scripts/prepare/make_office.py generate output/office --seed 7
    python -m hgnn --data output/office --target-relation accessed --out output/office-hgnn
    python scripts/prepare/make_office.py label output/office output/office-hgnn

generate writes nodes.csv and edges.csv (docs/scripts.md, data format), scenarios.json with hidden/ (the
appeals, see appeal_scenarios.py) and cases.json. Every seed gives another office: which
departments and sites it has, how many teams and documents, who holds which role. The office:

    employee -member_of-> team -part_of-> department      employee -works_in-> department
    employee -holds-> role                                 employee -reports_to-> employee (the manager)
    employee -located_in-> site -in_region-> region        employee -based_in-> region
    employee -works_on-> project -owned_by-> department    (two of their department's, sometimes
                                                            one more of another department)
    document -belongs_to-> project (two of its department's)  document -owned_by-> department
    document -stored_at-> site     document -stored_in-> region   document -classified_as-> classification
    employee -accessed-> document  (target relation: what the current policy allows)

The current policy: an employee reads the documents of the projects they work on, and the public
documents of their own department. Five hidden policies, which only an appeal can teach Corax:

    manager, coordinator   one holder per department, who reads every document of their department:
                           few users and pairs, a small rule
    regional_manager       a manager also reads every document stored in their region, of any
                           department: the same people, many more documents, a large rule
    security_officer       one per region, reads every document stored in their region: a large rule
    facility_manager       one per site, reads every document stored at their site: a large rule

cases.json, the cases a run through the gateway shows (each with the expected answers):

    1   policy_denied           the policy denies the request (BOLA); Corax's AI is not asked
    2   ai_allowed              the policy allows a summary (every employee may preview every document)
                                and the AI lets it pass: its risk is at most the threshold
    3   ai_denied               the policy allows a summary, the AI denies it: its risk is above the threshold
    4   appeal_rejected         an employee asks for access, the admin rejects the appeal
    5a  appeal_small_accepted   the admin approves; Corax's rule has a small scope: applied at once
    5b  appeal_small_rejected   the admin rejects an appeal whose rule would have been small: nothing applies
    5c  appeal_large_accepted   the admin approves; the rule is large: Corax asks again, the admin accepts
                                (a rule is policy: the AI still judges the colleague, who is denied if
                                their risk is above the threshold, as it usually is for a large rule)
    5d  appeal_large_declined   the admin approves; the rule is large, the admin declines: only the exception
    5e  appeal_large_accepted   a manager asks for a document of another department stored in their region:
                                the regional rule is large, the admin accepts it
    6   revoke                  the rule of 5a is revoked: its colleague is denied again, the exception stays

The threshold comes from training (hgnn/evaluate.py, calibrate_threshold): the risk 1 - p below which
target_pass_rate of the validation's real accesses fall. Which summaries the AI lets pass, and the
mean risk of a rule's scope (service/tier.py), are known only then: generate writes the candidates
of cases 2 and 3, and label picks them with the trained model and checks the tier of every rule.
"""

import argparse
import csv
import json
import random
import sys
from pathlib import Path

import appeal_scenarios

REPO = Path(__file__).resolve().parents[2]
DEPARTMENTS = ["sales", "engineering", "finance", "operations", "hr", "legal", "marketing", "procurement"]
REGIONS = {
    "emea": ["frankfurt", "amsterdam", "london", "paris"],
    "apac": ["singapore", "jakarta", "tokyo", "sydney"],
}
CLASSIFICATIONS = [("public", 0.3), ("internal", 0.5), ("confidential", 0.2)]
DEPARTMENT_ROLES = ["manager", "coordinator"]
ROLES = ["engineer", "analyst", *DEPARTMENT_ROLES, "security_officer", "facility_manager"]
ADMIN = "admin_01"  # the demo's admin: a JWT subject, not a node of the graph
PROJECTS = 4  # per department: an employee and a document each have two, so a few documents share none
POOL = 30  # candidates of cases 2 and 3
ATTEMPTS = 50
# the counting limits of a small rule (service/tier.py, TierLimits); its mean risk is checked by label
MAX_USERS, MAX_PAIRS = 5, 50

SAME_DEPARTMENT = {"kind": "shared", "relation": "works_in", "other": "owned_by"}
SAME_REGION = {"kind": "shared", "relation": "based_in", "other": "stored_in"}
HIDDEN = {
    **{role: (lambda e, d, r=role: e["role"] == r and d["department"] == e["department"],
              [SAME_DEPARTMENT, {"kind": "user_has", "relation": "holds", "other": f"role_{role}"}])
       for role in DEPARTMENT_ROLES},
    "regional_manager": (lambda e, d: e["role"] == "manager" and d["region"] == e["region"],
                         [SAME_REGION, {"kind": "user_has", "relation": "holds", "other": "role_manager"}]),
    "security_officer": (lambda e, d: e["role"] == "security_officer" and d["region"] == e["region"],
                         [SAME_REGION, {"kind": "user_has", "relation": "holds", "other": "role_security_officer"}]),
    "facility_manager": (lambda e, d: e["role"] == "facility_manager" and d["site"] == e["site"],
                         [{"kind": "shared", "relation": "located_in", "other": "stored_at"},
                          {"kind": "user_has", "relation": "holds", "other": "role_facility_manager"}]),
}  # fmt: skip
# who holds a hidden policy (its name, unless another role), and which of its documents an appeal asks
# for: a regional manager asks for one of another department, which the department rule does not open
HOLDER = {"regional_manager": "manager"}
ASKS = {"regional_manager": lambda e, d: d["department"] != e["department"]}
# the appeal cases: id -> (kind, hidden policy or None for a one-off, tier, what the admin does)
APPEALS = {
    "4": ("appeal_rejected", None, None, {"appeal": "reject"}),
    "5a": ("appeal_small_accepted", "manager", "small", {"appeal": "approve"}),
    "5b": ("appeal_small_rejected", "coordinator", "small", {"appeal": "reject"}),
    "5c": ("appeal_large_accepted", "security_officer", "large", {"appeal": "approve", "large_scope": "accept"}),
    "5d": ("appeal_large_declined", "facility_manager", "large", {"appeal": "approve", "large_scope": "decline"}),
    "5e": ("appeal_large_accepted", "regional_manager", "large", {"appeal": "approve", "large_scope": "accept"}),
}


class NoCase(Exception):
    """This office has no pair for a case; build() draws another."""


def build(seed: int, departments: int | None = None, documents: int | None = None):
    """nodes, edges, the appeal scenarios and cases.json of the office of this seed. A drawn office
    that lacks a case is drawn again from the same seed, so every seed gives one."""
    for attempt in range(ATTEMPTS):
        rng = random.Random(f"{seed}/{attempt}")
        office = draw(rng, departments, documents)
        try:
            scenarios, cases = choose_cases(rng, office)
        except NoCase:
            continue
        cases["seed"] = seed
        return office["nodes"], office["edges"], scenarios, cases
    raise RuntimeError(f"seed {seed}: no office with every case in {ATTEMPTS} attempts")


def draw(rng: random.Random, departments: int | None, documents: int | None) -> dict:
    """A random office: its nodes, edges, employees, documents and the pairs the policy allows."""
    chosen = sorted(rng.sample(DEPARTMENTS, departments or rng.randint(4, 5)))
    site_region = {site: region for region, sites in REGIONS.items() for site in rng.sample(sites, 2)}
    sites = sorted(site_region)
    nodes: list[tuple[str, str]] = [(f"role_{r}", "role") for r in ROLES]
    nodes += [(f"classification_{level}", "classification") for level, _ in CLASSIFICATIONS]
    nodes += [(f"region_{r}", "region") for r in sorted(set(site_region.values()))]
    edges: list[tuple[str, str, str]] = []
    for site in sites:
        nodes.append((f"site_{site}", "site"))
        edges.append((f"site_{site}", "in_region", f"region_{site_region[site]}"))

    owned: dict[str, list[str]] = {}
    teams: dict[str, list[str]] = {}
    for department in chosen:
        nodes.append((f"department_{department}", "department"))
        teams[department] = [f"team_{department}{t + 1}" for t in range(rng.randint(2, 4))]
        owned[department] = [f"project_{department}{p + 1}" for p in range(PROJECTS)]
        for team in teams[department]:
            nodes.append((team, "team"))
            edges.append((team, "part_of", f"department_{department}"))
        for project in owned[department]:
            nodes.append((project, "project"))
            edges.append((project, "owned_by", f"department_{department}"))

    employees: dict[str, dict] = {}
    for department in chosen:
        for team in teams[department]:
            for _ in range(rng.randint(5, 9)):
                site = rng.choice(sites)
                worked = rng.sample(owned[department], k=2)
                if rng.random() < 0.2:
                    worked.append(rng.choice(owned[rng.choice([d for d in chosen if d != department])]))
                employees[f"employee_E{len(employees) + 1:03d}"] = {
                    "department": department, "team": team, "site": site, "region": site_region[site],
                    "projects": worked, "role": "engineer" if department == "engineering" else "analyst",
                }  # fmt: skip

    # the roles: a manager and a coordinator per department, a security officer per region and a
    # facility manager per site, each held by someone drawn among those without a role yet
    def appoint(role: str, among: list[str]) -> str:
        holder = rng.choice([e for e in among if employees[e]["role"] in ("engineer", "analyst")])
        employees[holder]["role"] = role
        return holder

    for department in chosen:
        staff = [e for e, a in employees.items() if a["department"] == department]
        for role in DEPARTMENT_ROLES:
            appoint(role, staff)
    for region in sorted(set(site_region.values())):
        appoint("security_officer", [e for e, a in employees.items() if a["region"] == region])
    for site in sites:
        appoint("facility_manager", [e for e, a in employees.items() if a["site"] == site])
    manager = {a["department"]: e for e, a in employees.items() if a["role"] == "manager"}

    for employee, a in employees.items():
        nodes.append((employee, "employee"))
        edges += [
            (employee, "member_of", a["team"]),
            (employee, "works_in", f"department_{a['department']}"),
            (employee, "holds", f"role_{a['role']}"),
            (employee, "located_in", f"site_{a['site']}"),
            (employee, "based_in", f"region_{a['region']}"),
        ]
        edges += [(employee, "works_on", p) for p in a["projects"]]
        if a["role"] != "manager":
            edges.append((employee, "reports_to", manager[a["department"]]))

    docs: dict[str, dict] = {}
    levels, weights = zip(*CLASSIFICATIONS, strict=True)
    per_project = documents or rng.randint(5, 8)
    for department in chosen:
        for project in owned[department]:
            for _ in range(per_project):
                site = rng.choice(sites)
                document = f"document_D{len(docs) + 1:03d}"
                docs[document] = {
                    "department": department, "site": site, "region": site_region[site],
                    "projects": [project, rng.choice([p for p in owned[department] if p != project])],
                    "level": rng.choices(levels, weights)[0],
                }  # fmt: skip
                nodes.append((document, "document"))
                edges += [(document, "belongs_to", p) for p in docs[document]["projects"]]
                edges += [
                    (document, "owned_by", f"department_{department}"),
                    (document, "stored_at", f"site_{site}"),
                    (document, "stored_in", f"region_{site_region[site]}"),
                    (document, "classified_as", f"classification_{docs[document]['level']}"),
                ]

    permitted = {(e, d) for e in employees for d in docs if allowed(employees[e], docs[d])}
    edges += [(e, "accessed", d) for e, d in sorted(permitted)]
    return {"nodes": nodes, "edges": edges, "employees": employees, "docs": docs, "permitted": permitted}


def allowed(e: dict, d: dict) -> bool:
    """The current policy (demo/policy/app.rego): a project in common, or a public document
    of the employee's own department."""
    return bool(set(d["projects"]) & set(e["projects"])) or (
        d["level"] == "public" and d["department"] == e["department"]
    )


def choose_cases(rng: random.Random, office: dict) -> tuple[list[dict], dict]:
    """The appeal scenarios and cases.json; NoCase when this office lacks a pair for one."""
    employees, docs, permitted = office["employees"], office["docs"], office["permitted"]
    staff = [e for e, a in employees.items() if a["role"] in ("engineer", "analyst")]

    def opened(name: str, employee: str) -> list[str]:
        """The documents the hidden policy opens for the employee, that the current policy denies."""
        test = HIDDEN[name][0]
        return [d for d in docs if (employee, d) not in permitted and test(employees[employee], docs[d])]

    def pick(items):
        if not items:
            raise NoCase
        return rng.choice(sorted(items))

    def appellant_and_witness(name: str) -> tuple[tuple[str, str], tuple[str, str]]:
        """Someone the hidden policy opens a document for, and a colleague in the same situation
        who never appeals."""
        asks = ASKS.get(name, lambda e, d: True)

        def documents(e: str) -> list[str]:
            return [d for d in opened(name, e) if asks(employees[e], docs[d])]

        holders = [e for e, a in employees.items() if a["role"] == HOLDER.get(name, name) and documents(e)]
        if len(holders) < 2:
            raise NoCase
        user, witness = rng.sample(sorted(holders), 2)
        return (user, pick(documents(user))), (witness, pick(documents(witness)))

    def stranger(employee: str):
        """A confidential document of another department and region the employee may not read,
        that no hidden policy opens for them (they hold no role)."""
        e = employees[employee]
        return [d for d, a in docs.items() if (employee, d) not in permitted and a["department"] != e["department"]
                and a["region"] != e["region"] and a["level"] == "confidential"]  # fmt: skip

    def text(e: str) -> str:
        a = employees[e]
        return f"{e} ({a['role'].replace('_', ' ')}, {a['department'].title()}, {a['site'].title()})"

    def describe(d: str) -> str:
        a = docs[d]
        return f"{d} ({a['level']}, {a['department'].title()}, stored in {a['site'].title()})"

    cases = []
    # 1: the policy denies; the AI is only asked about what the policy allowed
    attacker = pick([e for e in staff if stranger(e)])
    target = pick(stranger(attacker))
    cases.append({
        "id": "1", "kind": "policy_denied", "user": attacker, "document": target,
        "title": f"{text(attacker)} reads {describe(target)} (BOLA)",
        "request": f"GET /documents/{target}", "expect": {"status": 403, "reason": "denied by policy", "ai": False},
    })  # fmt: skip

    # 2, 3: summaries, which the policy allows to every employee: usual pairs (the access
    # history) and unusual ones (another department and region); label picks one of each
    usual = sorted((e, d) for e, d in permitted if e in staff)
    unusual = sorted((e, d) for e in staff for d in stranger(e))
    for case, kind, pool, expect in (("2", "ai_allowed", usual, "risk <= threshold"),
                                     ("3", "ai_denied", unusual, "risk > threshold")):  # fmt: skip
        if not pool:
            raise NoCase
        cases.append({
            "id": case, "kind": kind, "user": None, "document": None, "title": None,
            "request": "GET /documents/:id/summary", "pool": rng.sample(pool, min(POOL, len(pool))),
            "expect": {"status": 200 if kind == "ai_allowed" else 403,
                       "reason": "allowed" if kind == "ai_allowed" else "high AI risk", "ai": expect},
        })  # fmt: skip

    # 4, 5a-5d: appeals
    scenarios = []
    for case, (kind, name, tier, admin) in APPEALS.items():
        if name is None:  # a one-off: someone without a role asks for a document of another department
            user = pick([e for e in staff if e != attacker and stranger(e)])
            (user, document), witness = (user, pick(stranger(user))), None
        else:
            (user, document), witness = appellant_and_witness(name)
        hidden = [(e, d) for e in employees for d in opened(name, e)] if name else []
        if name:  # the rule opens these pairs besides the appeal's own (patterns.opened_pairs)
            rest = [p for p in hidden if p != (user, document)]
            counted_small = len({e for e, _ in rest}) <= MAX_USERS and len(rest) <= MAX_PAIRS
            if counted_small != (tier == "small"):
                raise NoCase
        granted = admin["appeal"] == "approve"
        rule = granted and admin.get("large_scope", "accept") == "accept"
        entry = {
            "id": case, "kind": kind, "user": user, "document": document,
            "title": f"{text(user)} asks for {describe(document)}", "scenario": name or "one_off",
            "expected": HIDDEN[name][1] if name else None, "tier": tier, "admin": admin,
            "expect": {"before": 403, "after": 200 if granted else 403,
                       "corax": _corax(granted, tier, rule)},
        }  # fmt: skip
        if witness:  # opened: the rule allows the colleague's request; label asks the AI about it
            entry["witness"] = {"user": witness[0], "document": witness[1], "title": f"{text(witness[0])} never asks",
                                "before": 403, "after": 200 if rule else 403, "opened": rule}  # fmt: skip
        cases.append(entry)
        scenarios.append({
            "name": f"{case}_{name or 'one_off'}", "appeal": (user, document),
            "expected": HIDDEN[name][1] if name else None,
            "hidden_pairs": hidden,
        })  # fmt: skip

    small = next(c for c in cases if c["id"] == "5a")
    cases.append({
        "id": "6", "kind": "revoke", "revokes": "5a",
        "title": "the rule of case 5a is revoked (its file <appeal id>-rule.rego is deleted)",
        "expect": {"witness": {**{k: small["witness"][k] for k in ("user", "document")}, "after": 403},
                   "appellant": {"user": small["user"], "document": small["document"], "after": 200,
                                 "why": "the exact exception of the appeal stays"}},
    })  # fmt: skip
    return scenarios, {"admin": ADMIN, "verified": False, "threshold": None, "cases": cases}


def _corax(granted: bool, tier: str | None, rule: bool) -> str:
    if not granted:
        return "nothing written: the admin rejected the appeal"
    if tier == "small":
        return "exception, then the rule at once (small scope, no second confirmation)"
    if rule:
        return "exception; the rule answers 409 (large scope) until the admin acknowledges it, then it is written"
    return "exception; the rule answers 409 (large scope), the admin keeps only the exception"


def write(out_dir: Path, nodes, edges, scenarios, cases) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "nodes.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("id", "type"), *nodes])
    with (out_dir / "edges.csv").open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([("src", "relation", "dst"), *edges])
    appeal_scenarios.write(out_dir, "accessed", False, scenarios)
    (out_dir / "cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")


# --- label: the cases that depend on the trained model --------------------------------------


def read_graph(data_dir: Path) -> tuple[dict, dict]:
    """structure (relations without "accessed") and access, as the service has them."""
    structure: dict[str, dict[str, list[str]]] = {}
    access: dict[str, set[str]] = {}
    with (data_dir / "edges.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["relation"] == "accessed":
                access.setdefault(row["src"], set()).add(row["dst"])
            else:
                structure.setdefault(row["src"], {}).setdefault(row["relation"], []).append(row["dst"])
    return structure, {user: frozenset(objects) for user, objects in access.items()}


def label(cases: dict, structure: dict, access: dict, model) -> list[str]:
    """Pick the summaries of cases 2 and 3 and check each appeal's tier with the model, as the
    service would (patterns.opened_pairs, tier.assess). Returns the problems; cases is updated."""
    from patterns import Predicate, opened_pairs
    from tier import assess

    problems = []
    cases["threshold"] = model.threshold
    cases["target_pass_rate"] = model.metadata.get("risk_threshold", {}).get("target_pass_rate")
    users, objects = list(model.users), list(model.objects)

    def opens(case: dict) -> set:
        predicates = [Predicate(**p) for p in case["expected"]]
        return set(opened_pairs(structure, access, (case["user"], case["document"]), users, objects, predicates))

    # the rules a run applies (the admin accepts them); a colleague is shown only for a pair no other
    # of them opens, so the colleague's answer tells about this case's rule alone
    applied = {c["id"]: opens(c) for c in cases["cases"]
               if c.get("expected") and c["admin"]["appeal"] == "approve" and c["admin"].get("large_scope", "accept") == "accept"}  # fmt: skip
    # nor someone who appeals in the run: a colleague never asks
    appellants = {c["user"] for c in cases["cases"] if c.get("scenario")}
    for case in cases["cases"]:
        if case["kind"] in ("ai_allowed", "ai_denied"):
            scored = [(model.risk(u, d).risk, u, d) for u, d in case["pool"]]
            scored = [s for s in scored if s[0] is not None]
            if case["kind"] == "ai_allowed":
                fits = sorted(s for s in scored if s[0] <= model.threshold)
            else:
                fits = sorted((s for s in scored if s[0] > model.threshold), reverse=True)
            if not fits:
                problems.append(f"case {case['id']}: no candidate on the right side of {model.threshold:.4f}")
                continue
            risk, user, document = fits[0]
            case.update(user=user, document=document, risk=round(risk, 4),
                        request=f"GET /documents/{document}/summary",
                        title=f"{user} previews {document}: risk {risk:.4f} "
                              f"{'<=' if risk <= model.threshold else '>'} threshold {model.threshold:.4f}")  # fmt: skip
        elif case.get("expected"):
            predicates = [Predicate(**p) for p in case["expected"]]
            pairs = opened_pairs(structure, access, (case["user"], case["document"]), users, objects, predicates)
            scope = assess(pairs, model)
            case["scope"] = {"users": scope.users, "pairs": scope.pairs, "tier": scope.tier,
                             "mean_risk": None if scope.mean_risk is None else round(scope.mean_risk, 4),
                             "reasons": list(scope.reasons)}  # fmt: skip
            case["risk"] = model.risk(case["user"], case["document"]).risk
            witness = case.get("witness")
            if witness and witness["opened"]:
                # a rule is policy (policy/authz.rego): unlike the exception, the AI still judges what it
                # opens. The colleague is the one the AI lets through most easily, so the rule's effect
                # shows; if the AI denies every colleague, that is what the case shows.
                others = set().union(*(o for i, o in applied.items() if i != case["id"]))
                scored = [(model.risk(u, d).risk, u, d) for u, d in pairs if u not in appellants and (u, d) not in others]
                risk, user, document = min((s for s in scored if s[0] is not None), default=(None, None, None))
                if user is None:
                    risk = model.risk(witness["user"], witness["document"]).risk
                elif (user, document) != (witness["user"], witness["document"]):
                    witness.update(user=user, document=document, title=f"{user} never asks")
                witness.update(risk=round(risk, 4), after=200 if risk <= model.threshold else 403)
                if risk > model.threshold:
                    witness["why"] = f"the rule allows it, the AI denies it: risk {risk:.4f} > threshold"
                    if case["id"] == "5a":  # case 6 revokes this rule: it must have opened something
                        problems.append(f"case 5a: the AI denies the colleague (risk {risk:.4f}), so case 6 shows nothing")
            if scope.tier != case["tier"]:
                problems.append(f"case {case['id']}: the rule is {scope.tier}, the case needs {case['tier']} "
                                f"({'; '.join(scope.reasons) or 'within every limit'})")  # fmt: skip
    by_id = {case["id"]: case for case in cases["cases"]}
    for case in cases["cases"]:
        if case["kind"] == "revoke":  # the colleague the revoked rule opened, as label picked it
            witness = by_id[case["revokes"]]["witness"]
            case["expect"]["witness"].update(user=witness["user"], document=witness["document"])
    cases["verified"] = not problems
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a random office graph and its Corax cases.")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="the graph, scenarios.json and cases.json")
    generate.add_argument("out_dir", type=Path)
    generate.add_argument("--seed", type=int, default=0)
    generate.add_argument("--departments", type=int, choices=range(4, 6), help="default: 4 or 5, drawn")
    generate.add_argument("--documents", type=int, help="per project; default: 5 to 8, drawn")
    labelled = sub.add_parser("label", help="pick cases 2 and 3 and check the tiers with a trained model")
    labelled.add_argument("data_dir", type=Path)
    labelled.add_argument("model_dir", type=Path)
    args = parser.parse_args()

    if args.command == "generate":
        nodes, edges, scenarios, cases = build(args.seed, args.departments, args.documents)
        write(args.out_dir, nodes, edges, scenarios, cases)
        accessed = sum(e[1] == "accessed" for e in edges)
        print(f"{len(nodes)} nodes, {len(edges)} edges ({accessed} accessed) in {args.out_dir}")
        print(f"{len(cases['cases'])} cases in {args.out_dir / 'cases.json'}; "
              "train the model, then run label to pick cases 2 and 3")  # fmt: skip
        return

    sys.path.insert(0, str(REPO / "service"))
    from risk import RiskModel

    path = args.data_dir / "cases.json"
    cases = json.loads(path.read_text(encoding="utf-8"))
    problems = label(cases, *read_graph(args.data_dir), RiskModel.load(args.model_dir))
    path.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print(f"threshold {cases['threshold']:.4f}; {path} " + ("verified" if not problems else "NOT verified:"))
    for problem in problems:
        print(f"  {problem}")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
