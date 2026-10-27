import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class GraphData:
    structure: dict[str, dict[str, list[str]]]
    access: dict[str, frozenset[str]]
    node_types: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, model_dir: str | Path) -> "GraphData":
        model_dir = Path(model_dir)
        structure = json.loads((model_dir / "graph.json").read_text(encoding="utf-8"))
        access = json.loads((model_dir / "access.json").read_text(encoding="utf-8"))
        node_ids_file = model_dir / "node_ids.json"
        node_ids = json.loads(node_ids_file.read_text(encoding="utf-8")) if node_ids_file.exists() else {}
        node_types = {node: node_type for node_type, nodes in node_ids.items() for node in nodes}
        return cls(structure, {user: frozenset(objects) for user, objects in access.items()}, node_types)

    def has_access(self, user: str, obj: str) -> bool:
        return obj in self.access.get(user, ())

    def relation_types(self) -> dict[str, str]:
        # Relation name -> type of the nodes it points to, e.g. member_of -> department.
        found: dict[str, str] = {}
        for facts in self.structure.values():
            for relation, nodes in facts.items():
                if relation not in found:
                    known = next((self.node_types[n] for n in nodes if n in self.node_types), None)
                    if known:
                        found[relation] = known
        return found
