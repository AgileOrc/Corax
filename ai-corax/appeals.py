"""Appeal workflow behind POST /appeals (docs/ai-design.md, section 2.2).

An admin approved an appeal for one (user, object) pair:
    1. the exact exception is validated and written at once     -> <appeal id>-exception.rego
    2. similar cases and candidate patterns, narrowest first     -> awaiting_choice
       (no candidate: only the exception applies)               -> exception_only
    3. the admin picks a candidate (POST /appeals/<id>/pick); its scope sets the tier
       small: the rule is validated and written                  -> <appeal id>-rule.rego, applied
       large: it waits for POST /appeals/<id>/confirm            -> awaiting_confirmation
       POST /appeals/<id>/reject stops at any open step; the exception stays.

Rules are files in GENERATED_DIR, which OPA loads with --watch. Each appeal's state is
STATE_DIR/appeals/<appeal id>.json and every step is a line in STATE_DIR/audit.jsonl.
"""

import json
import logging
import subprocess
import threading
from dataclasses import asdict
from datetime import UTC, datetime

from config import Settings
from graph import GraphData
from patterns import Candidate, Predicate, candidates, opened_pairs
from risk import RiskModel
from rules import check_appeal_id, render_exception, render_rule
from similar import SimilarCase, SimilarityIndex
from tier import Scope, assess
from validate import Report, expected_decisions, validate, write_atomic

log = logging.getLogger("ai_corax")

# similar cases, as in scripts/similar_cases.py
K, MAX_PER_USER = 10, 2
OPEN = ("awaiting_choice", "awaiting_confirmation")


class AppealError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Appeals:
    def __init__(self, settings: Settings, model: RiskModel, graph: GraphData):
        self.settings, self.model, self.graph = settings, model, graph
        self.index = SimilarityIndex(model)
        self.folder = settings.state_dir / "appeals"
        self.audit = settings.state_dir / "audit.jsonl"
        self.folder.mkdir(parents=True, exist_ok=True)
        settings.generated_dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def submit(self, appeal_id: str, user: str, obj: str, action: str, admin: str) -> dict:
        with self.lock:
            _check_id(appeal_id)
            if (self.folder / f"{appeal_id}.json").exists():
                raise AppealError(f"appeal {appeal_id!r} already exists", 409)
            if user not in self.model.users:
                raise AppealError(f"unknown user {user!r}", 404)
            if obj not in self.model.objects:
                raise AppealError(f"unknown object {obj!r}", 404)
            if self.graph.has_access(user, obj):
                raise AppealError(f"{user!r} already has access to {obj!r}: nothing to appeal", 409)
            self.log("approved", appeal_id, user=user, object=obj, action=action, by=admin)

            # 1. the exact exception; similar cases are its negative examples
            cases = self.index.find(user, obj, K, self.graph.has_access, MAX_PER_USER)
            neighbours = [(c.user, c.object) for c in cases]
            exception = render_exception(appeal_id, user, action, obj)
            expected = {(user, obj): True, **dict.fromkeys(neighbours, False)}
            report = self._validate(exception, "app.exceptions", action, expected)
            if not report.ok:
                self.log("exception_rejected", appeal_id, checks=_checks(report))
                raise AppealError(f"the exception failed validation: {_failed(report)}", 500)
            exception_file = f"{appeal_id}-exception.rego"
            write_atomic(self.settings.generated_dir, exception_file, exception)
            self.log("exception_applied", appeal_id, file=exception_file)

            # 2. candidate patterns, narrowest first; the admin picks one
            found = candidates(
                self.graph.structure,
                self.graph.access,
                (user, obj),
                self.index.user_ids,
                self.index.object_ids,
                neighbours=neighbours,
                object_values=self.settings.object_values,
                object_identity=self.settings.object_identity,
            )
            state = {
                "appeal_id": appeal_id,
                "user": user,
                "object": obj,
                "action": action,
                "status": "awaiting_choice" if found else "exception_only",
                "approved_by": admin,
                "approved_at": _now(),
                "exception_file": exception_file,
                "similar": [self._case(c) for c in cases],
                "candidates": [_candidate(n, c) for n, c in enumerate(found, start=1)],
            }
            self.log("candidates", appeal_id, found=len(found), status=state["status"])
            self._save(state)
            return state

    def pick(self, appeal_id: str, number: int, admin: str) -> dict:
        with self.lock:
            state = self._load(appeal_id)
            if state["status"] != "awaiting_choice":
                raise AppealError(f"appeal {appeal_id!r} is {state['status']}", 409)
            if not 1 <= number <= len(state["candidates"]):
                raise AppealError(f"no candidate {number}; there are {len(state['candidates'])}")
            chosen = state["candidates"][number - 1]
            predicates = [Predicate(**p) for p in chosen["predicates"]]
            opened = self._opened(state, predicates)
            scope = assess(opened, self.model, self.settings.tier_limits)
            rule = render_rule(
                appeal_id,
                state["action"],
                predicates,
                {"users": scope.users, "pairs": scope.pairs, "tier": scope.tier},
            )
            state["picked"] = {
                "number": number,
                "pattern": chosen["pattern"],
                "predicates": chosen["predicates"],
                **_scope(scope),
                "rule": rule,
                "by": admin,
            }
            self.log("picked", appeal_id, number=number, pattern=chosen["pattern"],
                     tier=scope.tier, users=scope.users, pairs=scope.pairs, by=admin)  # fmt: skip
            if scope.tier == "large":
                state["status"] = "awaiting_confirmation"
                self.log("awaiting_confirmation", appeal_id, reasons=list(scope.reasons))
                self._save(state)
                return state
            return self._apply(state, predicates, opened)

    def confirm(self, appeal_id: str, admin: str) -> dict:
        with self.lock:
            state = self._load(appeal_id)
            if state["status"] != "awaiting_confirmation":
                raise AppealError(f"appeal {appeal_id!r} is {state['status']}", 409)
            predicates = [Predicate(**p) for p in state["picked"]["predicates"]]
            state["confirmed_by"] = admin
            self.log("confirmed", appeal_id, by=admin)
            return self._apply(state, predicates, self._opened(state, predicates))

    def reject(self, appeal_id: str, admin: str) -> dict:
        with self.lock:
            state = self._load(appeal_id)
            if state["status"] not in OPEN:
                raise AppealError(f"appeal {appeal_id!r} is {state['status']}", 409)
            state.update(status="rejected", rejected_by=admin)
            self.log("rejected", appeal_id, by=admin)
            self._save(state)
            return state

    def get(self, appeal_id: str) -> dict:
        with self.lock:
            return self._load(appeal_id)

    def _apply(self, state: dict, predicates: list[Predicate], opened: list) -> dict:
        appeal_id, rule = state["appeal_id"], state["picked"]["rule"]
        appeal = (state["user"], state["object"])
        expected = expected_decisions(
            self.graph.structure, predicates, opened, self.index.user_ids, self.index.object_ids,
            appeal,
        )  # fmt: skip
        report = self._validate(rule, "app.generated", state["action"], expected)
        state["validation"] = _checks(report)
        if report.ok:
            rule_file = f"{appeal_id}-rule.rego"
            write_atomic(self.settings.generated_dir, rule_file, rule)
            state.update(status="applied", rule_file=rule_file)
            self.log("rule_applied", appeal_id, file=rule_file)
        else:
            state["status"] = "rule_rejected"
            self.log("rule_rejected", appeal_id, checks=state["validation"])
        self._save(state)
        return state

    def _opened(self, state: dict, predicates: list[Predicate]) -> list:
        try:
            return opened_pairs(
                self.graph.structure, self.graph.access, (state["user"], state["object"]),
                self.index.user_ids, self.index.object_ids, predicates,
            )  # fmt: skip
        except ValueError as error:  # too many pairs to list a relational pattern exactly
            raise AppealError(str(error), 422) from error

    def _validate(self, rego: str, package: str, action: str, expected: dict) -> Report:
        settings = self.settings
        try:
            return validate(
                rego, package, action, self.graph.structure, expected,
                settings.opa_path, settings.policy_dir,
            )  # fmt: skip
        except (OSError, RuntimeError, subprocess.SubprocessError) as error:
            raise AppealError(f"validation could not run: {error}", 503) from error

    def _case(self, case: SimilarCase) -> dict:
        return {**asdict(case), "risk": self.model.risk(case.user, case.object).risk}

    def _load(self, appeal_id: str) -> dict:
        _check_id(appeal_id)
        path = self.folder / f"{appeal_id}.json"
        if not path.exists():
            raise AppealError(f"no appeal {appeal_id!r}", 404)
        return json.loads(path.read_text(encoding="utf-8"))

    def _save(self, state: dict) -> None:
        write_atomic(self.folder, f"{state['appeal_id']}.json", json.dumps(state, indent=1))

    def log(self, event: str, appeal_id: str, **details) -> None:
        line = {"time": _now(), "event": event, "appeal_id": appeal_id, **details}
        with self.audit.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
        log.info("appeal %s: %s %s", appeal_id, event, details)


def _check_id(appeal_id: str) -> None:
    try:
        check_appeal_id(appeal_id)
    except ValueError as error:
        raise AppealError(str(error)) from error


def _candidate(number: int, c: Candidate) -> dict:
    return {
        "number": number,
        "pattern": c.text(),
        "predicates": [asdict(p) for p in c.predicates],
        "users": c.users,
        "pairs": c.pairs,
        "estimated": c.estimated,
        "support": c.support,
        "examples": [list(pair) for pair in c.examples],
    }


def _scope(scope: Scope) -> dict:
    return {
        "tier": scope.tier,
        "users": scope.users,
        "pairs": scope.pairs,
        "mean_risk": scope.mean_risk,
        "reasons": list(scope.reasons),
    }


def _checks(report: Report) -> list[dict]:
    return [asdict(check) for check in report.checks]


def _failed(report: Report) -> str:
    return "; ".join(f"{c.name}: {c.detail}" for c in report.checks if not c.ok)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
