import json
import random
import re
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from config import Settings
from describe import Labels, describe_exception, describe_rule
from graph import GraphData
from patterns import Predicate, candidates, opened_pairs
from risk import RiskModel
from rules import APPEAL_ID, render_exception, render_rule
from similar import SimilarityIndex
from tier import assess
from validate import Report, expected_decisions, validate, write_atomic

ID_NUMBER = re.compile(r"^appeal-(\d+)$")
# How many users a 409 response lists. The preview endpoint lists all of them.
AFFECTED_IN_409 = 20


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
        self.lock = threading.Lock()
        self.user_type, _, self.object_type = model.metadata["target_edge_type"]
        self.relation_types = graph.relation_types()
        # (user, object) -> [(appeal id, "rule" or "exception", action)] for every access granted by an
        # appeal and not revoked. Built from the snapshots, so it survives a restart.
        self.usage_index: dict[tuple[str, str], list[tuple[str, str, str]]] = {}
        self.usage_lock = threading.Lock()
        for path in sorted(settings.appeals_dir.glob("appeal-*-granted.json")):
            appeal_id = path.name.removesuffix("-granted.json")
            self._index(appeal_id, json.loads(path.read_text(encoding="utf-8")))

    def describe(self, predicates, action: str) -> str:
        return describe_rule(
            predicates, action, self.user_type, self.object_type, self.relation_types, self.labels()
        )

    def labels(self) -> Labels:
        return Labels.load(self.settings.corax_config)

    def create(self, user: str, obj: str, action: str, reason: str | None, by: str | None) -> dict:
        if user not in self.model.users:
            raise AppealError(404, f"unknown user {user!r}")
        if obj not in self.model.objects:
            raise AppealError(404, f"unknown object {obj!r}")

        with self.lock:
            appeal_id = self._next_id()
            exception = render_exception(appeal_id, user, action, obj)
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
                "exception": {"description": describe_exception(user, action, obj, self.object_type, self.labels())},
                "neighbours": [
                    {"user": c.user, "object": c.object, "similarity": round(c.similarity, 4)}
                    for c in neighbours
                ],
                "candidates": [
                    _candidate(i, c, self.describe(c.predicates, action)) for i, c in enumerate(found, start=1)
                ],
                "files": {"exception": str(exception_file)},
                "history": [],
            }
            _event(record, "created", by)
            _event(record, "exception_applied", by)
            self._grant(record, "exception", record["exception"]["description"], [(user, obj)], by)
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

            chosen, predicates, opened = self._opened(record, candidate)
            appeal = (record["appeal"]["user"], record["appeal"]["object"])
            action = record["appeal"]["action"]
            description = self.describe(predicates, action)
            scope = assess(opened, self.model, self.settings.tier_limits)
            if scope.tier == "large" and not acknowledge_scope:
                raise AppealError(
                    409,
                    "this rule has a large scope; confirm again with acknowledge_scope=true",
                    {
                        "description": description,
                        "scope": asdict(scope),
                        "affected": affected(opened, limit=AFFECTED_IN_409),
                    },
                )

            rule = render_rule(
                appeal_id,
                action,
                predicates,
                {"users": scope.users, "pairs": scope.pairs, "tier": scope.tier, "approved_by": by or ""},
                description=description,
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
            record["chosen"] = {
                "candidate": candidate,
                "description": description,
                "pattern": chosen["pattern"],
                "scope": asdict(scope),
            }
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
            self._grant(record, "rule", description, opened, by)
            self._save(record)
        return record

    def revoke(self, appeal_id: str, exception: bool, by: str | None) -> dict:
        # Deletes the rule (and, if asked, the exception) and records who did it and when.
        with self.lock:
            record = self.get(appeal_id)
            snapshot = self.granted(appeal_id)
            kinds = [k for k in ("rule", "exception") if k in snapshot and not snapshot[k]["revoked"]]
            if not exception:
                kinds = [k for k in kinds if k == "rule"]
            if not kinds:
                raise AppealError(409, f"appeal {appeal_id} has nothing active to revoke")

            for kind in kinds:
                (self.settings.generated_dir / f"{appeal_id}-{kind}.rego").unlink(missing_ok=True)
                snapshot[kind]["revoked"] = {"by": by, "at": _now()}
                _event(record, f"{kind}_revoked", by)
            if "rule" in kinds:
                record["status"] = "rule_revoked"
            write_atomic(self.settings.appeals_dir, f"{appeal_id}-granted.json", json.dumps(snapshot, indent=2))
            self._save(record)
            with self.usage_lock:
                for key, entries in list(self.usage_index.items()):
                    self.usage_index[key] = [e for e in entries if not (e[0] == appeal_id and e[1] in kinds)]
                    if not self.usage_index[key]:
                        del self.usage_index[key]
        return record

    def record_use(self, user: str, obj: str, action: str | None, via: str) -> list[str]:
        # Called for every allowed request: /risk for rules, /usage for exceptions. Only access that an
        # appeal granted is written, to appeals/<id>-usage.jsonl. Returns the appeal ids it was written to.
        with self.usage_lock:
            entries = [
                (appeal_id, granted_action)
                for appeal_id, kind, granted_action in self.usage_index.get((user, obj), ())
                if kind == via and (action is None or action == granted_action)
            ]
            for appeal_id, granted_action in entries:
                line = json.dumps({"at": _now(), "user": user, "object": obj, "action": granted_action, "via": via})
                with (self.settings.appeals_dir / f"{appeal_id}-usage.jsonl").open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
        return [appeal_id for appeal_id, _ in entries]

    def _index(self, appeal_id: str, snapshot: dict) -> None:
        with self.usage_lock:
            for kind, granted in snapshot.items():
                if granted["revoked"]:
                    continue
                for entry in granted["access"]["by_user"]:
                    for obj in entry["objects"]:
                        found = self.usage_index.setdefault((entry["user"], obj), [])
                        if (appeal_id, kind, granted["action"]) not in found:
                            found.append((appeal_id, kind, granted["action"]))

    def rules(self) -> list[dict]:
        # Every rule and exception from an appeal that is still in effect, with who gained access and
        # how that access was used since, as data and as plain sentences for the admin.
        labels = self.labels()
        found = []
        for path in sorted(self.settings.appeals_dir.glob("appeal-*-granted.json")):
            appeal_id = path.name.removesuffix("-granted.json")
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            uses = self._uses(appeal_id)
            for kind in ("rule", "exception"):
                granted = snapshot.get(kind)
                if not granted or granted["revoked"]:
                    continue
                kind_uses = [u for u in uses if u["via"] == kind]
                entry = {
                    "appeal": appeal_id,
                    "kind": kind,
                    "description": granted["description"],
                    "approved_by": granted["approved_by"],
                    "at": granted["at"],
                    "file_missing": not (self.settings.generated_dir / f"{appeal_id}-{kind}.rego").exists(),
                    "access": granted["access"],
                    "usage": _usage_summary(kind_uses),
                }
                entry["summary"] = self._summary(entry, kind_uses, labels)
                found.append(entry)
        return found

    def access_of(self, user: str) -> list[str]:
        # The objects a user can reach through access granted by an appeal and not revoked.
        with self.usage_lock:
            return sorted({obj for (u, obj), entries in self.usage_index.items() if u == user and entries})

    def _uses(self, appeal_id: str) -> list[dict]:
        path = self.settings.appeals_dir / f"{appeal_id}-usage.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _summary(self, entry: dict, uses: list[dict], labels: Labels) -> list[str]:
        access, objects = entry["access"], labels.type(self.object_type)
        lines = [entry["description"]]
        how = "a rule" if entry["kind"] == "rule" else "an exception"
        lines.append(f"Approved as {how} by {entry['approved_by']} on {_readable(entry['at'])}.")
        lines.append(
            f"{_count(access['users'], 'person', 'people')} gained access to {_count(access['objects'], objects, objects + 's')}."
        )
        if entry["file_missing"]:
            lines.append("Warning: the rule file is missing, but it was not revoked through Corax.")
        if not uses:
            lines.append("Not used yet.")
            return lines
        people = len({u["user"] for u in uses})
        lines.append(f"Used {_count(len(uses), 'time', 'times')} by {_count(people, 'person', 'people')}:")
        lines += [
            f"  {_readable(u['at'])}  {labels.node(u['user'])} {labels.action(u['action'] or '')} {labels.node(u['object'])}".rstrip()
            for u in uses
        ]
        return lines

    def granted(self, appeal_id: str) -> dict:
        # The snapshot of who gained access to what, written when access was granted.
        self.get(appeal_id)
        path = self.settings.appeals_dir / f"{appeal_id}-granted.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _grant(self, record: dict, kind: str, description: str, pairs, by: str | None) -> None:
        snapshot = self.granted(record["id"]) if kind == "rule" else {}
        snapshot[kind] = {
            "description": description,
            "action": record["appeal"]["action"],
            "approved_by": by,
            "at": _now(),
            "revoked": None,
            "access": affected(pairs),
        }
        path = write_atomic(self.settings.appeals_dir, f"{record['id']}-granted.json", json.dumps(snapshot, indent=2))
        record["files"]["granted"] = str(path)
        self._index(record["id"], {kind: snapshot[kind]})

    def preview(self, appeal_id: str, candidate: int) -> dict:
        # Who would gain access to what if the admin accepted this candidate. Nothing is written.
        record = self.get(appeal_id)
        if not 1 <= candidate <= len(record["candidates"]):
            raise AppealError(404, f"appeal {appeal_id} has no candidate {candidate}")
        chosen, predicates, opened = self._opened(record, candidate)
        return {
            "appeal": appeal_id,
            "candidate": candidate,
            "description": self.describe(predicates, record["appeal"]["action"]),
            "pattern": chosen["pattern"],
            "scope": asdict(assess(opened, self.model, self.settings.tier_limits)),
            "affected": affected(opened),
        }

    def _opened(self, record: dict, candidate: int) -> tuple[dict, list[Predicate], list[tuple[str, str]]]:
        chosen = record["candidates"][candidate - 1]
        predicates = [Predicate(**p) for p in chosen["predicates"]]
        try:
            opened = opened_pairs(
                self.graph.structure,
                self.graph.access,
                (record["appeal"]["user"], record["appeal"]["object"]),
                self.index.user_ids,
                self.index.object_ids,
                predicates,
            )
        except ValueError as error:
            raise AppealError(422, str(error)) from error
        return chosen, predicates, opened

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
        # Only appeal-NNNN, so the snapshot and usage files next to a record cannot be read as one.
        if not APPEAL_ID.match(appeal_id) or not ID_NUMBER.match(appeal_id):
            raise AppealError(404, f"unknown appeal {appeal_id!r}")
        return self.settings.appeals_dir / f"{appeal_id}.json"

    def _save(self, record: dict) -> None:
        write_atomic(self.settings.appeals_dir, f"{record['id']}.json", json.dumps(record, indent=2))


def affected(pairs, limit: int | None = None) -> dict:
    # The (user, object) pairs grouped by user, the way an admin reads them.
    by_user: dict[str, list[str]] = {}
    for user, obj in pairs:
        by_user.setdefault(user, []).append(obj)
    users = sorted(by_user)
    shown = users if limit is None else users[:limit]
    return {
        "users": len(users),
        "objects": len({obj for _, obj in pairs}),
        "pairs": len(pairs),
        "by_user": [{"user": user, "objects": sorted(by_user[user])} for user in shown],
        "more_users": len(users) - len(shown),
    }


def _candidate(index: int, c, description: str) -> dict:
    return {
        "index": index,
        "description": description,
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


def _usage_summary(uses: list[dict]) -> dict:
    by_user: dict[str, dict[str, int]] = {}
    for u in uses:
        objects = by_user.setdefault(u["user"], {})
        objects[u["object"]] = objects.get(u["object"], 0) + 1
    return {
        "uses": len(uses),
        "users": len(by_user),
        "last": uses[-1]["at"] if uses else None,
        "by_user": [{"user": user, "objects": objects} for user, objects in sorted(by_user.items())],
    }


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _readable(at: str) -> str:
    return datetime.fromisoformat(at).strftime("%d %b %Y %H:%M UTC")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _event(record: dict, event: str, by: str | None) -> None:
    record["history"].append({"at": _now(), "event": event, "by": by})
