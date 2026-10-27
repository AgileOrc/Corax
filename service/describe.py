# Plain-language sentences for the rules an admin reviews. The Rego file is still what OPA enforces:
# the sentence is built from the same predicates, so it cannot say something the rule does not do.
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from patterns import Predicate


@dataclass(frozen=True)
class Labels:
    # Optional readable names from corax.config.labels in the application's data.json.
    actions: Mapping[str, str] = field(default_factory=dict)
    types: Mapping[str, str] = field(default_factory=dict)
    relations: Mapping[str, str] = field(default_factory=dict)
    nodes: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, config_file: Path | None) -> "Labels":
        if config_file is None:
            return cls()
        try:
            labels = json.loads(config_file.read_text(encoding="utf-8"))["corax"]["config"].get("labels", {})
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return cls()
        if not isinstance(labels, dict):
            return cls()
        return cls(**{key: _strings(labels.get(key)) for key in ("actions", "types", "relations", "nodes")})

    def action(self, action: str) -> str:
        return self.actions.get(action, action)

    def type(self, node_type: str) -> str:
        return self.types.get(node_type, node_type)

    def relation(self, relation: str) -> str:
        return self.relations.get(relation, relation.replace("_", " "))

    def node(self, node: str) -> str:
        return self.nodes.get(node, node)


def _strings(value) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}


def describe_rule(
    predicates: Sequence[Predicate],
    action: str,
    user_type: str,
    object_type: str,
    relation_types: Mapping[str, str],
    labels: Labels | None = None,
) -> str:
    labels = labels or Labels()
    user, obj = labels.type(user_type), labels.type(object_type)
    conditions = [_condition(p, user, obj, relation_types, labels) for p in predicates]
    return f"{_article(user).capitalize()} {user} may {labels.action(action)} {_article(obj)} {obj} when {_join(conditions)}."


def describe_exception(user: str, action: str, obj: str, object_type: str, labels: Labels | None = None) -> str:
    labels = labels or Labels()
    return f"{labels.node(user)} may {labels.action(action)} {labels.node(obj)}, an exception for this one {labels.type(object_type)} only."


def _condition(p: Predicate, user: str, obj: str, relation_types: Mapping[str, str], labels: Labels) -> str:
    if p.kind == "user_has":
        return f"the {user} {labels.relation(p.relation)} {labels.node(p.other)}"
    if p.kind == "object_has":
        return f"the {obj} {labels.relation(p.relation)} {labels.node(p.other)}"
    if p.kind == "shared":
        user_side, object_side = relation_types.get(p.relation), relation_types.get(p.other)
        if user_side and user_side == object_side:
            return f"the {user} and the {obj} have the same {labels.type(user_side)}"
        return f"the {user}'s {labels.relation(p.relation)} matches the {obj}'s {labels.relation(p.other)}"
    if p.kind == "direct":
        return f"the {user} {labels.relation(p.relation)} the {obj}"
    if p.kind == "object_is":
        return f"the {obj} is {labels.node(p.other)}"
    raise ValueError(f"unknown predicate kind {p.kind!r}")


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def _join(parts: list[str]) -> str:
    if len(parts) <= 2:
        return " and ".join(parts)
    return ", ".join(parts[:-1]) + ", and " + parts[-1]
