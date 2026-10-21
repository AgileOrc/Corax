import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GraphData:
    structure: dict[str, dict[str, list[str]]]
    access: dict[str, frozenset[str]]

    @classmethod
    def load(cls, model_dir: str | Path) -> "GraphData":
        model_dir = Path(model_dir)
        structure = json.loads((model_dir / "graph.json").read_text(encoding="utf-8"))
        access = json.loads((model_dir / "access.json").read_text(encoding="utf-8"))
        return cls(structure, {user: frozenset(objects) for user, objects in access.items()})

    def has_access(self, user: str, obj: str) -> bool:
        return obj in self.access.get(user, ())
