"""Random cases of the office (scripts/prepare/make_office.py) recorded through the real gateway.

    python scripts/demo_office.py prepare --seed 7
    docker-compose -f deploy/docker-compose.yml down -v
    docker-compose -f deploy/docker-compose.yml up -d --build
    python scripts/demo_office_cases.py --count 200 --seed 1

Each case is drawn at random from the paths a request can take: denied by the policy; allowed by the
policy and let through by the AI; allowed by the policy and denied by the AI; an appeal the admin
rejects (after Corax's dry run shows what it would find); an appeal the admin approves whose rule is
small (written at once) or large (Corax asks again: the admin accepts or declines); and a rule that is
revoked after it was written. The cases do not say which path they take: every request is sent through
Envoy and recorded as it happened, with Envoy's reason and risk (its access log), the risk computed
from the embeddings (risk = 1 - sigmoid(h_user . h_document)), the tier's three variables, and the
policy files Corax wrote or the admin deleted (read from the service's container).

Every case starts from the stack's own policy: after an appeal the script deletes the files it
created, so the cases do not depend on each other. Writes output/gateway/cases_<count>.json and .md
(the cases) and cases_<count>_key.json (which path each case took, to check an answer against).
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

import demo_backend
import demo_gateway
import make_office
from config import Settings
from graph import GraphData
from patterns import Predicate, candidates, opened_pairs
from risk import RiskModel, _sigmoid
from similar import SimilarityIndex, closest
from tier import TierLimits, assess

KINDS = ["policy_denied", "ai_allowed", "ai_denied", "appeal_rejected", "appeal_small_accepted",
         "appeal_small_rejected", "appeal_large_accepted", "appeal_large_declined", "revoke"]  # fmt: skip
SMALL, LARGE = ["manager", "coordinator"], ["regional_manager", "security_officer", "facility_manager"]
LIMITS = TierLimits(max_user_share=0.06)  # the service's (AUTO_APPLY_MAX_USER_SHARE in deploy/docker-compose.yml)
CANDIDATES = 8  # the service's APPEAL_CANDIDATES (deploy/docker-compose.yml leaves the default)
TRIM = 240  # longer strings of a response body (a document's content) are cut


class Office:
    """The office graph and the trained model, as the stack has them."""

    def __init__(self, data: Path, hgnn: Path):
        self.structure, self.access = make_office.read_graph(data)
        self.model = RiskModel.load(hgnn)
        self.users, self.objects = list(self.model.users), list(self.model.objects)
        self.meta = self.model.metadata
        self.hidden = {name: [Predicate(**p) for p in make_office.HIDDEN[name][1]] for name in SMALL + LARGE}
        self.opened = {name: [(u, d) for u in self.users for d in self.objects
                              if not self.reads(u, d) and holds(self.structure, preds, u, d)]
                       for name, preds in self.hidden.items()}  # fmt: skip
        graph = GraphData.load(hgnn)
        self.graph, self.index = graph, SimilarityIndex(self.model)

    def offers(self, user: str, document: str, name: str) -> bool:
        """Whether the appeal's candidates (as service/appeals.py finds them) include the pattern."""
        if getattr(self, "index", None) is None:
            return True
        s = Settings(model_dir=Path("."))  # the service's defaults (deploy/docker-compose.yml sets none)
        neighbours = closest(self.index.find(user, document, s.similar_max, self.graph.has_access), s.similar_min, s.similar_margin)
        found = candidates(self.graph.structure, self.graph.access, (user, document), self.index.user_ids,
                           self.index.object_ids, neighbours=[(c.user, c.object) for c in neighbours])  # fmt: skip
        wanted = {(p.kind, p.relation, p.other) for p in self.hidden[name]}
        return any({(p.kind, p.relation, p.other) for p in c.predicates} == wanted for c in found[:CANDIDATES])

    def role(self, user: str) -> str:
        return self.structure[user]["holds"][0].removeprefix("role_")

    def who(self, user: str) -> str:
        s = self.structure[user]
        return (f"{user} ({self.role(user).replace('_', ' ')}, {_name(s['works_in'][0])}, "
                f"{_name(s['located_in'][0])})")  # fmt: skip

    def what(self, document: str) -> str:
        s = self.structure[document]
        return (f"{document} ({_name(s['classified_as'][0])}, {_name(s['owned_by'][0])}, "
                f"stored at {_name(s['stored_at'][0])})")  # fmt: skip

    def reads(self, user: str, document: str) -> bool:
        return document in self.access.get(user, ())

    def risk(self, user: str, document: str) -> dict:
        """risk = 1 - sigmoid(h_user . h_document), as service/risk.py computes it."""
        dot = float(self.model.users[user] @ self.model.objects[document])
        result = self.model.risk(user, document)
        return {"dot": round(dot, 4), "sigmoid": float(f"{_sigmoid(dot):.6g}"), "risk": result.risk,
                "threshold": round(self.model.threshold, 6), "high_risk": result.high_risk}  # fmt: skip

    def app_policy(self, user: str, document: str, summary: bool) -> str | None:
        """Why demo/policy/app.rego allows the request, or None."""
        if summary:
            return "app.authz: every employee may preview the summary of every document"
        s, d = self.structure[user], self.structure[document]
        shared = sorted(set(s.get("works_on", [])) & set(d.get("belongs_to", [])))
        if shared:
            return f"app.authz: they work on {', '.join(shared)}, which the document belongs to"
        if "classification_public" in d["classified_as"] and set(s["works_in"]) & set(d["owned_by"]):
            return "app.authz: a public document of their own department"
        return None


def _name(node: str) -> str:
    return node.split("_", 1)[1].replace("_", " ").title()


def holds(structure: dict, predicates: list[Predicate], user: str, document: str) -> bool:
    for p in predicates:
        if p.kind == "shared" and not set(structure[user].get(p.relation, [])) & set(structure[document].get(p.other, [])):
            return False
        if p.kind == "user_has" and p.other not in structure[user].get(p.relation, []):
            return False
    return True


# --- drawing the cases ------------------------------------------------------------------------


def draw(office: Office, count: int, rng: random.Random) -> list[dict]:
    """count plans, no case twice: every kind at least once, the rest of kinds drawn at random. An
    office has only so many cases of some kinds (a small rule opens at most 5 people and 50 pairs, so
    there are few small appeals); once a kind has no new case, the others fill the count."""
    plans, seen = [], set()

    def take(kind: str) -> bool:
        for _ in range(500):
            plan = _plan(office, kind, rng, seen)
            if plan:
                seen.add((plan["kind"], plan["user"], plan["document"], plan.get("route")))
                plans.append(plan)
                return True
        return False

    for kind in KINDS:
        if not take(kind):
            sys.exit(f"no {kind} case in this office")
    left = list(KINDS)
    while len(plans) < count:
        if not left:
            sys.exit(f"this office has only {len(plans)} different cases; ask for fewer, or prepare a bigger one")
        kind = rng.choice(left)
        if not take(kind):
            left.remove(kind)
    rng.shuffle(plans)
    return plans


def _plan(office: Office, kind: str, rng: random.Random, seen: set = frozenset()) -> dict:
    users, objects, thr = office.users, office.objects, office.model.threshold
    if kind == "policy_denied":
        user = rng.choice(users)
        document = rng.choice([d for d in objects if not office.reads(user, d)])
        plan = {"kind": kind, "user": user, "document": document, "route": "read"}
        return {} if (kind, user, document, "read") in seen else plan
    if kind in ("ai_allowed", "ai_denied"):
        low = kind == "ai_allowed"
        for _ in range(200):
            user = rng.choice(users)
            if rng.random() < 0.3 and office.access.get(user):  # a document they may read
                route, document = "read", rng.choice(sorted(office.access[user]))
            else:  # a summary: the policy allows every pair, the AI judges it
                route, document = "summary", rng.choice(objects)
            if (office.model.risk(user, document).risk <= thr) == low and (kind, user, document, route) not in seen:
                return {"kind": kind, "user": user, "document": document, "route": route}
        return {}
    if kind == "appeal_rejected":
        name = rng.choice([None, None, *LARGE])  # a one-off, or someone a large rule would cover
    elif kind in ("appeal_small_accepted", "appeal_small_rejected"):
        name = rng.choice(SMALL)
    elif kind in ("appeal_large_accepted", "appeal_large_declined"):
        name = rng.choice(LARGE)
    else:  # revoke: a rule the admin accepted, small or large
        name = rng.choice(SMALL + LARGE)
    if name is None:
        covered = {pair for pairs in office.opened.values() for pair in pairs}
        user = rng.choice([u for u in users if office.role(u) in ("engineer", "analyst")])
        document = rng.choice([d for d in objects if not office.reads(user, d) and (user, d) not in covered])
    else:
        pairs = office.opened[name]
        if name in make_office.ASKS:  # a regional manager asks for a document of another department
            pairs = [(u, d) for u, d in pairs if not set(office.structure[u]["works_in"]) & set(office.structure[d]["owned_by"])]
        user, document = rng.choice(pairs)
    if (kind, user, document, None) in seen:  # before the costly checks below
        return {}
    plan = {"kind": kind, "user": user, "document": document, "pattern": name}
    if name and kind != "appeal_rejected" and not kind.endswith("small_rejected"):
        opened = opened_pairs(office.structure, office.access, (user, document), users, objects, office.hidden[name])
        scope = assess(opened, office.model, LIMITS)
        if (scope.tier == "small") != (name in SMALL) or not office.offers(user, document, name):
            return {}
        others = [(office.model.risk(u, d).risk, u, d) for u, d in opened if u != user]
        if others:  # the colleague the AI lets through most easily, so the rule's effect shows
            _, plan["colleague_user"], plan["colleague_document"] = min(others)
    return plan


# --- recording them through the gateway -------------------------------------------------------


class Recorder:
    def __init__(self, office: Office, stack: "demo_backend.Stack", admin: str):
        self.office, self.stack, self.admin = office, stack, admin
        self.exceptions: set[tuple[str, str]] = set()
        self.rules: list[tuple[str, list[Predicate], str]] = []  # appeal id, predicates, pattern
        self.mismatches: list[str] = []
        self.checked = 0  # requests whose answer was checked

    # one request ----------------------------------------------------------------------------

    def get(self, user: str, document: str, summary: bool, note: str, wait: bool = False) -> dict:
        """A document request through Envoy, with what the policy and the AI make of it."""
        path = f"/documents/{document}" + ("/summary" if summary else "")
        o = self.office
        exception = not summary and (user, document) in self.exceptions
        rule = next((r for r in self.rules if not summary and holds(o.structure, r[1], user, document)), None)
        policy = o.app_policy(user, document, summary) or (rule and f"app.generated ({rule[0]}): {rule[2]}")
        risk = o.risk(user, document)
        if exception:
            want, reason = 200, "allowed by appeal exception"
        elif not policy:
            want, reason = 403, "denied by policy"
        elif risk["high_risk"]:
            want, reason = 403, "high AI risk"
        else:
            want, reason = 200, "allowed"

        deadline = time.time() + (10 if wait else 0)
        while True:
            status, body, log = self.stack.call("GET", path, None, bearer=demo_gateway.token(user))
            if status == want or time.time() >= deadline:
                break
            time.sleep(0.25)
        self.checked += 1
        if status != want or log.get("reason") != reason:
            self.mismatches.append(f"{note}: GET {path} as {user}: {status} {log.get('reason')!r}, "
                                   f"expected {want} {reason!r}")  # fmt: skip
        step = {
            "step": note,
            "request": {"method": "GET", "path": path, "as": user,
                        "headers": {"Authorization": f"Bearer <JWT HS256: sub={user}, iss=corax-demo, aud=corax-demo-api>"}},
            "policy": ("app.exceptions: the exact pair an admin approved (the AI is not asked)" if exception
                       else policy or "no rule of app.authz or app.generated allows it"),
            "ai": ({**risk, "verdict": (f"{risk['risk']:.4f} > {risk['threshold']:.4f}: high risk, denied" if risk["high_risk"]
                                        else f"{risk['risk']:.4f} <= {risk['threshold']:.4f}: lets it pass")}
                   if policy and not exception else "not asked"),
            "response": {"status": status, "body": _trim(body)},
            "reason": log.get("reason"),
            "envoy_risk": log.get("risk"),
            "as_expected": status == want and log.get("reason") == reason,
        }  # fmt: skip
        return step

    def post(self, path: str, body: dict, note: str) -> tuple[int, dict, dict]:
        status, answer, log = self.stack.call("POST", path, None, body, bearer=demo_gateway.token(self.admin))
        step = {"step": note,
                "request": {"method": "POST", "path": path, "as": self.admin, "body": body,
                            "headers": {"Authorization": f"Bearer <JWT HS256: sub={self.admin}, iss=corax-demo, aud=corax-demo-api>",
                                        "Content-Type": "application/json"}},
                "response": {"status": status, "body": _appeal_body(answer)},
                "reason": log.get("reason")}  # fmt: skip
        return status, answer, step

    # one case -------------------------------------------------------------------------------

    def record(self, number: int, plan: dict) -> dict:
        o, kind, user, document = self.office, plan["kind"], plan["user"], plan["document"]
        case = {"id": number, "user": o.who(user), "document": o.what(document), "steps": []}
        steps = case["steps"]
        if kind in ("policy_denied", "ai_allowed", "ai_denied"):
            summary = plan["route"] == "summary"
            case["title"] = f"{user} {'previews' if summary else 'opens'} {document}"
            steps.append(self.get(user, document, summary, "the request"))
            return case

        case["title"] = f"{user} asks for access to {document}"
        steps.append(self.get(user, document, False, "the request, before any appeal"))
        reason = f"{o.role(user).replace('_', ' ')} asks to read {document}"
        if kind in ("appeal_rejected", "appeal_small_rejected"):
            body = {"user": user, "object": document, "action": "read", "reason": reason, "dry_run": True}
            status, preview, step = self.post("/corax/appeals", body, "the admin looks at Corax's dry run (nothing is written)")
            steps.append(step)
            if status == 200 and preview.get("candidates"):
                case["candidates"] = compare(o, (user, document), preview["candidates"], 1)
            if status == 200 and preview.get("scope"):
                case["tier"] = _tier(preview["scope"], f"candidate #1: {preview['candidates'][0]['pattern']}")
            case["admin"] = "rejects the appeal"
            case["policy_change"] = [{"change": "none", "detail": "the admin rejected the appeal: Corax writes nothing"}]
            steps.append(self.get(user, document, False, "the request after the rejection"))
            return case

        written: list[str] = []
        try:
            self._approved(case, plan, reason, written)
        finally:
            self._clean(written, user, document)
        return case

    def _approved(self, case: dict, plan: dict, reason: str, written: list[str]) -> None:
        o, kind, steps = self.office, plan["kind"], case["steps"]
        user, document = plan["user"], plan["document"]
        body = {"user": user, "object": document, "action": "read", "reason": reason}
        status, record, step = self.post("/corax/appeals", body, "the admin approves: Corax writes the exact exception")
        steps.append(step)
        if status != 201:
            self.mismatches.append(f"case {case['id']}: the appeal answered {status}")
            return
        appeal = record["id"]
        written.append(f"{appeal}-exception.rego")
        self.exceptions.add((user, document))
        changes = case["policy_change"] = [{"change": "added", "file": f"/runtime/generated/{appeal}-exception.rego",
                                            "rego": self.stack.read_generated(f"{appeal}-exception.rego")}]  # fmt: skip

        wanted = {(p.kind, p.relation, p.other) for p in o.hidden[plan["pattern"]]}
        chosen = next((c for c in record["candidates"]
                       if {(p["kind"], p["relation"], p["other"]) for p in c["predicates"]} == wanted), None)  # fmt: skip
        if chosen is None:
            self.mismatches.append(f"case {case['id']}: Corax did not offer {plan['pattern']}'s pattern")
            return
        case["candidates"] = compare(o, (user, document), record["candidates"], chosen["index"])
        path = f"/corax/appeals/{appeal}/confirm"
        status, answer, step = self.post(path, {"candidate": chosen["index"]},
                                         f"the admin picks pattern #{chosen['index']}: {chosen['pattern']}")  # fmt: skip
        steps.append(step)
        if status == 409 and "scope" in answer:
            case["tier"] = _tier(answer["scope"], chosen["pattern"])
            if kind == "appeal_large_declined":
                case["admin"] = "approves the appeal, then declines the large rule"
                status, answer, step = self.post(path, {"candidate": None}, "the admin declines the large scope: only the exception stays")
            else:
                case["admin"] = "approves the appeal, then accepts the large rule (acknowledge_scope)"
                status, answer, step = self.post(path, {"candidate": chosen["index"], "acknowledge_scope": True},
                                                 "the admin accepts the large scope")  # fmt: skip
            steps.append(step)
        elif status == 200 and answer.get("chosen"):
            case["tier"] = _tier(answer["chosen"]["scope"], chosen["pattern"])
            case["admin"] = "approves the appeal; the rule is small, so Corax writes it at once"
        if status != 200:
            self.mismatches.append(f"case {case['id']}: the confirmation answered {status}")
            return
        if answer["status"] == "rule_applied":
            written.append(f"{appeal}-rule.rego")
            self.rules.append((appeal, o.hidden[plan["pattern"]], chosen["pattern"]))
            changes.append({"change": "added", "file": f"/runtime/generated/{appeal}-rule.rego",
                            "rego": self.stack.read_generated(f"{appeal}-rule.rego")})  # fmt: skip

        steps.append(self.get(user, document, False, "the appellant after the decision", wait=True))
        colleague = plan.get("colleague_user"), plan.get("colleague_document")
        if colleague[0]:
            case["colleague"] = f"{o.who(colleague[0])} never asks; the rule's pattern covers {o.what(colleague[1])}"
            time.sleep(0 if answer["status"] == "rule_applied" else 1)
            steps.append(self.get(*colleague, False, "a colleague who never asked", wait=answer["status"] == "rule_applied"))
        if kind == "revoke" and answer["status"] == "rule_applied":
            name = f"{appeal}-rule.rego"
            self.stack.delete_generated(name)
            written.remove(name)
            self.rules = [r for r in self.rules if r[0] != appeal]
            case["admin"] += "; later the admin revokes the rule"
            changes.append({"change": "deleted", "file": f"/runtime/generated/{name}",
                            "detail": "revoked: OPA reloads without it (--watch); the exception stays"})  # fmt: skip
            steps.append({"step": "the admin revokes the rule", "action": f"delete /runtime/generated/{name}"})
            time.sleep(1)
            if colleague[0]:
                steps.append(self.get(*colleague, False, "the colleague after the revoke", wait=True))
            steps.append(self.get(user, document, False, "the appellant after the revoke (the exception stays)"))

    def _clean(self, written: list[str], user: str, document: str) -> None:
        """Back to the stack's own policy, so the next case does not depend on this one."""
        for name in written:
            self.stack.delete_generated(name)
        self.rules = [r for r in self.rules if f"{r[0]}-rule.rego" not in written]
        self.exceptions.discard((user, document))
        if written:
            deadline = time.time() + 10
            while time.time() < deadline and self.stack.call("GET", f"/documents/{document}", None,
                                                             bearer=demo_gateway.token(user))[0] != 403:  # fmt: skip
                time.sleep(0.25)


def compare(office: Office, appeal: tuple[str, str], found: list[dict], chosen: int) -> list[dict]:
    """The candidates as sets: the new pairs each pattern opens (service/patterns.py opened_pairs, the
    pairs the tier counts), and which of them is a subset of which. A pattern with one more condition
    opens a subset of the one without it (a team within a department, a role within a department)."""
    sets = []
    for c in found:
        try:
            sets.append(frozenset(opened_pairs(office.structure, office.access, appeal, office.users, office.objects,
                                               [Predicate(**p) for p in c["predicates"]])))  # fmt: skip
        except ValueError:  # too many pairs to list exactly
            sets.append(None)
    rows = []
    for c, mine in zip(found, sets, strict=True):
        row = {"index": c["index"], "pattern": c["pattern"], "chosen": c["index"] == chosen}
        if mine is not None:
            others = [(o["index"], s) for o, s in zip(found, sets, strict=True) if o is not c and s is not None]
            row.update(users=len({u for u, _ in mine}), pairs=len(mine),
                       subset_of=[i for i, s in others if mine < s], contains=[i for i, s in others if s < mine],
                       same_as=[i for i, s in others if s == mine])  # fmt: skip
        rows.append(row)
    return rows


def _tier(scope: dict, pattern: str) -> dict:
    mean = scope["mean_risk"]
    return {
        "pattern": pattern,
        "users": {"value": scope["users"], "share": round(scope["user_share"], 4), "limit": LIMITS.max_user_share,
                  "within": scope["user_share"] <= LIMITS.max_user_share},
        "pairs": {"value": scope["pairs"], "limit": LIMITS.max_pairs, "within": scope["pairs"] <= LIMITS.max_pairs},
        "mean_risk": {"value": None if mean is None else round(mean, 4), "limit": LIMITS.max_mean_risk,
                      "within": mean is None or mean <= LIMITS.max_mean_risk,
                      "how": "the mean of 1 - sigmoid(h_user . h_document) over the pairs the rule opens"},
        "tier": scope["tier"],
        "why": "; ".join(scope["reasons"]) or "all three within their limits",
    }  # fmt: skip


def _trim(value):
    if isinstance(value, dict):
        return {k: _trim(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_trim(v) for v in value]
    if isinstance(value, str) and len(value) > TRIM:
        return value[:TRIM] + " ..."
    return value


def _appeal_body(answer: dict) -> dict:
    """The service's answer without the long parts (neighbours, examples, history, file paths)."""
    if not isinstance(answer, dict):
        return answer
    keep = {k: v for k, v in answer.items() if k not in ("neighbours", "history", "files", "appeal")}
    if "chosen" in keep or keep.get("status") == "exception_only":  # the candidates were listed when it was created
        keep.pop("candidates", None)
    if "candidates" in keep:
        keep["candidates"] = [{k: c[k] for k in ("index", "pattern", "users", "pairs")} for c in keep["candidates"]]
    if "validation" in keep:
        keep["validation"] = [f"{'ok' if c['ok'] else 'FAILED'}: {c['name']}" for c in keep["validation"]]
    return keep


# --- writing them -------------------------------------------------------------------------------


def threshold_block(office: Office) -> dict:
    t = office.meta["risk_threshold"]
    return {
        "risk": "risk = 1 - sigmoid(h_user . h_document): h are the HGNN's embeddings (hgnn/, exported to embeddings.npz)",
        "threshold": round(t["value"], 6),
        "how": (f"hgnn/evaluate.py calibrate_threshold: the {t['target_pass_rate']:.0%} quantile (interpolation 'higher') "
                "of 1 - p over the validation's real accesses, so that share of real access passes"),
        "target_pass_rate": t["target_pass_rate"],
        "validation": {"false_deny_rate": round(t["val_false_deny_rate"], 4), "detection_rate": round(t["val_detection_rate"], 4),
                       "auc": round(office.meta["val_auc"], 4)},
        "decision": "OPA (policy/authz.rego): allow = admin OR exception OR (policy AND NOT risk > threshold)",
        "tier_limits": {"max_user_share": LIMITS.max_user_share, "max_pairs": LIMITS.max_pairs, "max_mean_risk": LIMITS.max_mean_risk,
                        "rule": "small if all three are within their limits (written at once), else large (the admin must acknowledge)"},
    }  # fmt: skip


def text_header(header: dict) -> list[str]:
    v = header["validation"]
    return [f"risk = 1 - sigmoid(h_user . h_document); threshold {header['threshold']:.4f} "
            f"({header['target_pass_rate']:.0%} of the validation's real accesses pass; AUC {v['auc']}, "
            f"real accesses denied {v['false_deny_rate']}, unusual pairs detected {v['detection_rate']})",
            header["decision"],
            f"tier: small if the share of users <= {LIMITS.max_user_share:.0%}, new pairs <= {LIMITS.max_pairs} and mean risk <= "
            f"{LIMITS.max_mean_risk} (written at once), else large (the admin must acknowledge)"]  # fmt: skip


def text(case: dict) -> list[str]:
    """One case for the terminal, as traffic: no number and no name of the path it takes, and
    everything in the order it happens."""
    changes = {c.get("file", ""): c for c in case.get("policy_change", [])}
    lines = [f"[{time.strftime('%H:%M:%S')}] {case['user']}  ->  {case['document']}"]
    tier_shown = False

    def code(name_end: str) -> None:
        change = next((c for f, c in changes.items() if f.endswith(name_end) and c["change"] == "added"), None)
        if change:
            lines.append(f"   policy code added: {change['file']}")
            lines.extend(f"      {line}" for line in change["rego"].splitlines() if line and not line.startswith("#"))

    def tier() -> None:
        nonlocal tier_shown
        if "tier" in case and not tier_shown:
            t, tier_shown = case["tier"], True
            lines.append(f"   tier {t['tier']}: users {t['users']['value']} (limit {t['users']['limit']}), pairs "
                         f"{t['pairs']['value']} (limit {t['pairs']['limit']}), mean risk {t['mean_risk']['value']} "
                         f"(limit {t['mean_risk']['limit']}): {t['why']}")  # fmt: skip

    for step in case["steps"]:
        if "action" in step:  # the revoke
            lines.append(f"   {step['step']}: {step['action']}")
            deleted = next((c for c in changes.values() if c["change"] == "deleted"), None)
            if deleted:
                lines.append(f"   policy code deleted: {deleted['file']} ({deleted['detail']})")
            continue
        r, status, answer = step["request"], step["response"]["status"], step["response"]["body"]
        if "policy" in step:
            if "colleague" in step["step"] and step["step"].startswith("a colleague"):
                lines.append(f"   meanwhile {case['colleague']}")
            mark = "" if step.get("as_expected", True) else "  !! not as expected"
            lines.append(f"   {r['method']} {r['path']} as {r['as']} -> {status} ({step['reason']}){mark}")
            lines.append(f"      policy: {step['policy']}")
            ai = step["ai"]
            lines.append(f"      AI: risk = 1 - sigmoid({ai['dot']}) = {ai['risk']:.4f}; {ai['verdict']}"
                         if isinstance(ai, dict) else f"      AI: {ai}")  # fmt: skip
            continue
        said = answer
        if isinstance(answer, dict):
            said = answer.get("status") or answer.get("error") or ("dry run, nothing written" if answer.get("dry_run") else "")
        lines.append(f"   {step['step']}")
        lines.append(f"   {r['method']} {r['path']} as {r['as']} {json.dumps(r.get('body', {}))} -> {status} {said}")
        if r["path"] == "/corax/appeals":  # created (or a dry run): the candidates
            if status == 201:
                code("-exception.rego")
            lines.append("   candidates (the new pairs each pattern opens, as sets; * the one the admin looks at):")
            for c in case.get("candidates", []):
                rel = "; ".join(f"{name} {', '.join(f'#{i}' for i in c[key])}" for key, name in
                                (("subset_of", "subset of"), ("contains", "contains"), ("same_as", "same as")) if c.get(key))  # fmt: skip
                lines.append(f"     {'*' if c['chosen'] else ' '}#{c['index']} users={c.get('users', '?'):>3} "
                             f"pairs={c.get('pairs', '?'):>4}  {c['pattern']}" + (f"  ({rel})" if rel else ""))  # fmt: skip
            if status == 200:  # the dry run: the admin decides on what it shows
                tier()
                lines.append(f"   admin {case['admin']}")
                lines.append("   policy code: unchanged (the admin rejected the appeal: Corax writes nothing)")
        elif isinstance(answer, dict) and (status == 409 or answer.get("status") == "rule_applied"):
            if not tier_shown and "admin" in case:
                tier()
                lines.append(f"   admin {case['admin'].removesuffix('; later the admin revokes the rule')}")
            if answer.get("status") == "rule_applied":
                code("-rule.rego")
        elif isinstance(answer, dict) and answer.get("status") == "exception_only":
            lines.append("   policy code: no rule (only the exception stays)")
    return lines


def markdown(header: dict, cases: list[dict]) -> str:
    lines = ["# Corax office cases", "", "## Risk and threshold", "",
             f"- {header['risk']}", f"- threshold = **{header['threshold']}**: {header['how']}",
             f"- validation: AUC {header['validation']['auc']}, real accesses denied {header['validation']['false_deny_rate']}, "
             f"unusual pairs detected {header['validation']['detection_rate']}", f"- {header['decision']}",
             f"- tier: share of users <= {LIMITS.max_user_share:.0%}, new pairs <= {LIMITS.max_pairs}, mean risk <= {LIMITS.max_mean_risk}: "
             f"{header['tier_limits']['rule']}", ""]  # fmt: skip
    for case in cases:
        lines += ["---", "", f"## Case {case['id']}: {case['title']}", "", f"- user: {case['user']}",
                  f"- document: {case['document']}"]  # fmt: skip
        if case.get("colleague"):
            lines.append(f"- colleague: {case['colleague']}")
        lines.append("")
        for step in case["steps"]:
            lines += _step(step)
        if "candidates" in case:
            lines += ["**Candidates as sets** (the new pairs each pattern opens; A ⊂ B: every pair A opens, B opens "
                      "too; * the one the admin picked, or #1 of the dry run):", "",
                      "| # | pattern | users | pairs | ⊂ subset of | ⊃ contains | = same as |", "|---|---|---|---|---|---|---|"]  # fmt: skip
            for c in case["candidates"]:
                refs = lambda key: ", ".join(f"#{i}" for i in c.get(key, [])) or "-"  # noqa: E731,B023
                lines.append(f"| {c['index']}{' *' if c['chosen'] else ''} | `{c['pattern']}` | {c.get('users', '?')} | "
                             f"{c.get('pairs', '?')} | {refs('subset_of')} | {refs('contains')} | {refs('same_as')} |")  # fmt: skip
            lines.append("")
        if "tier" in case:
            t = case["tier"]
            lines += [f"**Tier** of `{t['pattern']}`:", "", "| variable | value | limit | within |", "|---|---|---|---|"]
            for name in ("users", "pairs", "mean_risk"):
                v = t[name]
                lines.append(f"| {name} | {v['value']} | {v['limit']} | {'yes' if v['within'] else 'no'} |")
            lines += ["", f"-> **{t['tier']}** ({t['why']}); mean risk = {t['mean_risk']['how']}", ""]
        if "admin" in case:
            lines += [f"**Admin**: {case['admin']}", ""]
        if "policy_change" in case:
            lines += ["**Policy code**:", ""]
            for change in case["policy_change"]:
                if change["change"] == "none":
                    lines += [f"- no change: {change['detail']}", ""]
                elif change["change"] == "deleted":
                    lines += [f"- deleted `{change['file']}`: {change['detail']}", ""]
                else:
                    lines += [f"- added `{change['file']}`:", "", "```rego", change["rego"].rstrip(), "```", ""]
    return "\n".join(lines) + "\n"


def _step(step: dict) -> list[str]:
    lines = [f"**{step['step'][0].upper()}{step['step'][1:]}**", ""]
    if "action" in step:
        return lines + [f"`{step['action']}`", ""]
    r = step["request"]
    head = [f"{r['method']} {r['path']} HTTP/1.1", *(f"{k}: {v}" for k, v in r["headers"].items())]
    lines += ["```http", *head, *([""] + [json.dumps(r["body"])] if "body" in r else []), "```", ""]
    if "policy" in step:
        lines.append(f"- policy: {step['policy']}")
        ai = step["ai"]
        if isinstance(ai, dict):
            lines.append(f"- AI: risk = 1 - sigmoid({ai['dot']}) = 1 - {ai['sigmoid']:.6g} = {ai['risk']:.7g}; "
                         f"threshold {ai['threshold']}: {ai['verdict']}")  # fmt: skip
        else:
            lines.append(f"- AI: {ai}")
    body = json.dumps(step["response"]["body"], indent=1) if step["response"]["body"] else "(empty)"
    lines += [f"- response: **{step['response']['status']}**", f"- reason (Envoy): `{step.get('reason')}`"
              + (f", risk (Envoy) `{step['envoy_risk']}`" if step.get("envoy_risk") else ""), "",
              "```json", body, "```", ""]  # fmt: skip
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1, help="which cases are drawn")
    parser.add_argument("--gateway", default="http://localhost:8080")
    parser.add_argument("--project", help="compose project of the stack (default: found from docker)")
    parser.add_argument("--quiet", action="store_true", help="only a counter in the terminal; the cases go to the files")
    args = parser.parse_args()
    if args.count < len(KINDS):
        sys.exit(f"--count must be at least {len(KINDS)}, one case per path")

    out = demo_gateway.OUT
    data, hgnn = out / "data", out / "hgnn"
    office_cases = json.loads((data / "cases.json").read_text(encoding="utf-8"))
    office = Office(data, hgnn)
    plans = draw(office, args.count, random.Random(args.seed))
    stack = demo_backend.Stack(args.gateway, "", args.project)
    recorder = Recorder(office, stack, office_cases["admin"])
    if stack.generated():
        sys.exit(f"the stack already holds generated files ({', '.join(stack.generated())}): start a fresh one "
                 "(docker-compose -f deploy/docker-compose.yml down -v, then up -d)")  # fmt: skip

    header = threshold_block(office)
    if not args.quiet:
        print("\n".join(text_header(header)) + "\n", flush=True)
    cases, key = [], []
    for number, plan in enumerate(plans, start=1):
        cases.append(recorder.record(number, plan))
        key.append({"id": number, "path": plan["kind"]})
        if args.quiet:
            print(f"\r{number}/{len(plans)} cases", end="", flush=True)
        else:
            print("\n".join(text(cases[-1])) + "\n", flush=True)
    print()

    bad = len(recorder.mismatches)
    print(f"{recorder.checked - bad} of {recorder.checked} requests answered as expected "
          "(200 = forwarded to the document store, 403 = denied at the gateway)")  # fmt: skip
    stem = out / f"cases_{args.count}"
    stem.with_suffix(".json").write_text(json.dumps({"corax": header, "cases": cases}, indent=2), encoding="utf-8")
    stem.with_suffix(".md").write_text(markdown(header, cases), encoding="utf-8")
    (out / f"cases_{args.count}_key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    print(f"{len(cases)} cases in {stem}.json and {stem}.md; which path each took: {stem}_key.json")
    for mismatch in recorder.mismatches:
        print(f"  differs: {mismatch}")
    sys.exit(1 if recorder.mismatches else 0)


if __name__ == "__main__":
    main()
