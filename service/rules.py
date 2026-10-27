import json
import re
from collections.abc import Sequence

from patterns import Predicate

APPEAL_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
USER, OBJECT = "data.corax.graph[input.user.id]", "data.corax.graph[input.resource.id]"


def literal(value: str) -> str:
    return json.dumps(value)


def check_appeal_id(appeal_id: str) -> str:
    if not APPEAL_ID.match(appeal_id):
        raise ValueError(f"invalid appeal id {appeal_id!r}")
    return appeal_id


def conditions(predicates: Sequence[Predicate]) -> list[str]:
    lines, shared = [], 0
    for p in predicates:
        if p.kind == "user_has":
            lines.append(f"{literal(p.other)} in {USER}[{literal(p.relation)}]")
        elif p.kind == "object_has":
            lines.append(f"{literal(p.other)} in {OBJECT}[{literal(p.relation)}]")
        elif p.kind == "shared":
            shared += 1
            lines.append(f"some n{shared} in {USER}[{literal(p.relation)}]")
            lines.append(f"n{shared} in {OBJECT}[{literal(p.other)}]")
        elif p.kind == "direct":
            lines.append(f"input.resource.id in {USER}[{literal(p.relation)}]")
        elif p.kind == "object_is":
            lines.append(f"input.resource.id == {literal(p.other)}")
        else:
            raise ValueError(f"unknown predicate kind {p.kind!r}")
    return lines


def _rule(package: str, metadata: dict, body: list[str]) -> str:
    meta = [f"# {key}: {json.dumps(value)}" for key, value in metadata.items() if key != "custom"]
    custom = [
        f"#   {key}: {json.dumps(value)}" for key, value in metadata.get("custom", {}).items()
    ]
    lines = [f"package {package}", "", "# METADATA", *meta]
    if custom:
        lines += ["# custom:", *custom]
    lines += ["allow if {", *(f"\t{line}" for line in body), "}", ""]
    return "\n".join(lines)


def render_rule(
    appeal_id: str,
    action: str,
    predicates: Sequence[Predicate],
    custom: dict | None = None,
    description: str | None = None,
) -> str:
    check_appeal_id(appeal_id)
    pattern = " AND ".join(p.text() for p in predicates)
    # With a plain-language description, the technical pattern moves to custom.pattern.
    extra = {"pattern": pattern} if description else {}
    metadata = {
        "title": appeal_id,
        "description": description or pattern,
        "custom": {"appeal_id": appeal_id, **extra, **(custom or {})},
    }
    body = [f"input.action == {literal(action)}", *conditions(predicates)]
    return _rule("app.generated", metadata, body)


def render_exception(appeal_id: str, user: str, action: str, obj: str) -> str:
    check_appeal_id(appeal_id)
    metadata = {
        "title": f"{appeal_id} exception",
        "description": f"{user} may {action} {obj}",
        "custom": {"appeal_id": appeal_id},
    }
    body = [
        f"input.user.id == {literal(user)}",
        f"input.resource.id == {literal(obj)}",
        f"input.action == {literal(action)}",
    ]
    return _rule("app.exceptions", metadata, body)
