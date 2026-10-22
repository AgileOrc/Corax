import json
import random
import re
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from config import Settings
from graph import GraphData
from patterns import Predicate, candidates, opened_pairs
from risk import RiskModel
from rules import APPEAL_ID, render_exception, render_rule
from similar import SimilarityIndex
from tier import assess
from validate import Report, expected_decisions, validate, write_atomic

ID_NUMBER = re.compile(r"^appeal-(\d+)$")


class AppealError(Exception):
    def __init__(self, status: int, message: str, detail: dict | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail or {}


class AppealService:
    def __init__(self, model: RiskModel, graph: GraphData, settings: Settings):
        self.model = model
        self.graph = graph
        self.index = SimilarityIndex(model)
        self.settings = settings
        # generated files only hold for this kind of resource (rules.type_check)
        self.resource_type = settings.resource_type or model.metadata["target_edge_type"][2]
        self.lock = threading.Lock()

    def create(self, user: str, obj: str, action: str, reason: str | None, by: str | None) -> dict:
        if user not in self.model.users:
            raise AppealError(404, f"unknown user {user!r}")
        if obj not in self.model.objects:
            raise AppealError(404, f"unknown object {obj!r}")
        if self.graph.has_access(user, obj):
            raise AppealError(409, f"{user} already has access to {obj}: there is nothing to appeal")

        with self.lock:
            appeal_id = self._next_id()
            exception = render_exception(appeal_id, user, action, obj, self.resource_type)
            report = self._validate(exception, "app.exceptions", action, self._exception_pairs(user, obj))
            if not report.ok:
                raise AppealError(422, "the exception failed validation", {"validation": _checks(report)})
            exception_file = write_atomic(self.settings.generated_dir, f"{appeal_id}-exception.rego", exception)

            neighbours = self.index.find(user, obj, 10, self.graph.has_access)
            found = candidates(
                self.graph.structure,
                self.graph.access,
                (user, obj),
                self.index.user_ids,
                self.index.object_ids,
                neighbours=[(c.user, c.object) for c in neighbours],
                object_identity=self.settings.object_identity,
            )[: self.settings.candidates]

            record = {
                "id": appeal_id,
                "status": "exception_applied",
                "appeal": {"user": user, "object": obj, "action": action, "reason": reason},
                "neighbours": [
                    {"user": c.user, "object": c.object, "similarity": round(c.similarity, 4)}
                    for c in neighbours
                ],
                "candidates": [_candidate(i, c) for i, c in enumerate(found, start=1)],
                "files": {"exception": str(exception_file)},
                "history": [],
            }
            _event(record, "created", by)
            _event(record, "exception_applied", by)
            self._save(record)
        return record

    def get(self, appeal_id: str) -> dict:
        path = self._path(appeal_id)
        if not path.exists():
            raise AppealError(404, f"unknown appeal {appeal_id!r}")
        return json.loads(path.read_text(encoding="utf-8"))

    def confirm(self, appeal_id: str, candidate: int | None, acknowledge_scope: bool, by: str | None) -> dict:
        with self.lock:
            record = self.get(appeal_id)
            if record["status"] != "exception_applied":
                raise AppealError(409, f"appeal {appeal_id} is already {record['status']}")

            if candidate is None:
                record["status"] = "exception_only"
                _event(record, "exception_only", by)
                self._save(record)
                return record

            if not 1 <= candidate <= len(record["candidates"]):
                raise AppealError(422, f"candidate must be between 1 and {len(record['candidates'])}")

            chosen = record["candidates"][candidate - 1]
            predicates = [Predicate(**p) for p in chosen["predicates"]]
            appeal = (record["appeal"]["user"], record["appeal"]["object"])
            action = record["appeal"]["action"]
            try:
                opened = opened_pairs(
                    self.graph.structure,
                    self.graph.access,
                    appeal,
                    self.index.user_ids,
                    self.index.object_ids,
                    predicates,
                )
            except ValueError as error:
                raise AppealError(422, str(error)) from error

            scope = assess(opened, self.model, self.settings.tier_limits)
            if scope.tier == "large" and not acknowledge_scope:
                raise AppealError(
                    409,
                    "this rule has a large scope; confirm again with acknowledge_scope=true",
                    {"scope": asdict(scope)},
                )

            rule = render_rule(
                appeal_id,
                action,
                predicates,
                {"users": scope.users, "pairs": scope.pairs, "tier": scope.tier, "approved_by": by or ""},
                self.resource_type,
            )
            expected = expected_decisions(
                self.graph.structure,
                predicates,
                opened,
                self.index.user_ids,
                self.index.object_ids,
                appeal,
            )
            report = self._validate(rule, "app.generated", action, expected)
            record["chosen"] = {"candidate": candidate, "pattern": chosen["pattern"], "scope": asdict(scope)}
            record["validation"] = _checks(report)
            if not report.ok:
                record["status"] = "rule_rejected"
                _event(record, "rule_rejected", by)
                self._save(record)
                raise AppealError(422, "the rule failed validation", {"validation": record["validation"]})

            rule_file = write_atomic(self.settings.generated_dir, f"{appeal_id}-rule.rego", rule)
            record["files"]["rule"] = str(rule_file)
            record["status"] = "rule_applied"
            _event(record, "rule_applied", by)
            self._save(record)
        return record

    def _validate(self, rego: str, package: str, action: str, expected: dict) -> Report:
        try:
            return validate(
                rego,
                package,
                action,
                self.graph.structure,
                expected,
                self.settings.opa_path,
                self.settings.policy_dir,
                self.resource_type,
            )
        except (OSError, RuntimeError) as error:
            raise AppealError(503, f"opa is not available: {error}") from error

    def _exception_pairs(self, user: str, obj: str) -> dict:
        rng = random.Random(0)
        users, objects = self.index.user_ids, self.index.object_ids
        pairs = {(user, obj)}
        pairs.update((rng.choice(users), obj) for _ in range(20))
        pairs.update((user, rng.choice(objects)) for _ in range(20))
        pairs.update((rng.choice(users), rng.choice(objects)) for _ in range(100))
        return {pair: pair == (user, obj) for pair in pairs}

    def _next_id(self) -> str:
        self.settings.appeals_dir.mkdir(parents=True, exist_ok=True)
        numbers = [
            int(match.group(1))
            for path in self.settings.appeals_dir.glob("appeal-*.json")
            if (match := ID_NUMBER.match(path.stem))
        ]
        return f"appeal-{max(numbers, default=0) + 1:04d}"

    def _path(self, appeal_id: str) -> Path:
        if not APPEAL_ID.match(appeal_id):
            raise AppealError(404, f"unknown appeal {appeal_id!r}")
        return self.settings.appeals_dir / f"{appeal_id}.json"

    def _save(self, record: dict) -> None:
        write_atomic(self.settings.appeals_dir, f"{record['id']}.json", json.dumps(record, indent=2))


def _candidate(index: int, c) -> dict:
    return {
        "index": index,
        "pattern": c.text(),
        "predicates": [asdict(p) for p in c.predicates],
        "users": c.users,
        "pairs": c.pairs,
        "estimated": c.estimated,
        "support": round(c.support, 4),
        "examples": [list(pair) for pair in c.examples],
    }


def _checks(report: Report) -> list[dict]:
    return [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in report.checks]


def _event(record: dict, event: str, by: str | None) -> None:
    record["history"].append(
        {"at": datetime.now(UTC).isoformat(timespec="seconds"), "event": event, "by": by}
    )
