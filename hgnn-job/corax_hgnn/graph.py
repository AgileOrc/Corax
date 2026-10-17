"""Load a typed graph from nodes.csv and edges.csv into a PyTorch Geometric HeteroData object.
The file format is described in docs/data-format.md.
"""

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import torch
import torch_geometric.transforms as T
from torch_geometric.data import HeteroData

EdgeType = tuple[str, str, str]


@dataclass
class Graph:
    data: HeteroData
    # node type -> node ids, in the same order as the rows of that type's embedding matrix
    node_ids: dict[str, list[str]]
    # the edge type used for link prediction
    target: EdgeType
    # the reverse edge type added by ToUndirected
    target_reverse: EdgeType


def read_rows(path: Path, columns: list[str]) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path.name}: missing column(s) {missing}")
        return list(reader)


def load_graph(folder: str | Path, target_relation: str) -> Graph:
    folder = Path(folder)

    # 1. Nodes: give every node an index inside its own type.
    node_ids: dict[str, list[str]] = defaultdict(list)
    index: dict[str, tuple[str, int]] = {}  # node id -> (type, index within type)
    for line, row in enumerate(read_rows(folder / "nodes.csv", ["id", "type"]), start=2):
        node_id, node_type = row["id"], row["type"]
        if node_id in index:
            raise ValueError(f"nodes.csv line {line}: duplicate node id {node_id!r}")
        index[node_id] = (node_type, len(node_ids[node_type]))
        node_ids[node_type].append(node_id)

    # 2. Edges: group by (source type, relation, destination type).
    edges: dict[EdgeType, tuple[list[int], list[int]]] = defaultdict(lambda: ([], []))
    rows = read_rows(folder / "edges.csv", ["src", "relation", "dst"])
    for line, row in enumerate(rows, start=2):
        for column in ("src", "dst"):
            if row[column] not in index:
                raise ValueError(f"edges.csv line {line}: unknown node {row[column]!r}")
        src_type, src_idx = index[row["src"]]
        dst_type, dst_idx = index[row["dst"]]
        sources, destinations = edges[(src_type, row["relation"], dst_type)]
        sources.append(src_idx)
        destinations.append(dst_idx)

    # 3. Checks that keep training meaningful.
    targets = [edge_type for edge_type in edges if edge_type[1] == target_relation]
    if len(targets) != 1:
        raise ValueError(
            f"target relation {target_relation!r} must connect exactly one pair of node types, "
            f"found {len(targets)}"
        )
    used_types = {t for (src, _, dst) in edges for t in (src, dst)}
    unused = sorted(set(node_ids) - used_types)
    if unused:
        raise ValueError(f"node type(s) without any edge: {unused}")

    # 4. Build HeteroData. ToUndirected adds a reverse edge type for every edge type,
    #    so messages flow both ways (as in the paper).
    data = HeteroData()
    for node_type, ids in node_ids.items():
        data[node_type].num_nodes = len(ids)
        data[node_type].node_id = torch.arange(len(ids))
    for edge_type, (sources, destinations) in edges.items():
        data[edge_type].edge_index = torch.tensor([sources, destinations], dtype=torch.long)
    data = T.ToUndirected()(data)

    target = targets[0]
    target_reverse = (target[2], f"rev_{target[1]}", target[0])
    return Graph(data=data, node_ids=dict(node_ids), target=target, target_reverse=target_reverse)
