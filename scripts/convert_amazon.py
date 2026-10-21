# Source: https://archive.ics.uci.edu/dataset/216/amazon+access+samples
# Command: python scripts/convert_amazon.py datasets/amzn-anon-access-samples-2.0.csv datasets/amazon-graph

import argparse
import csv
import sys
import time
from collections import Counter
from pathlib import Path

RESOURCE_PREFIXES = ("HOST_", "PERMGROUP_", "SYSTEM_SUPPORT_")
TARGET_RELATION = "has_potential_access"

# (relation, node type, column with the attribute value)
ATTRIBUTE_EDGES = [
    ("belongs_to", "department", "PERSON_DEPTNAME"),
    ("works_as", "title", "PERSON_BUSINESS_TITLE"),
    ("supervised_by", "manager", "PERSON_MGR_ID"),
]


def convert(source: Path, out_dir: Path) -> dict[str, Counter]:
    """Stream the source file row by row (it does not fit in memory) and write the graph."""
    out_dir.mkdir(parents=True, exist_ok=True)
    csv.field_size_limit(sys.maxsize if sys.maxsize < 2**31 else 2**31 - 1)

    attribute_nodes: dict[str, set[str]] = {node_type: set() for _, node_type, _ in ATTRIBUTE_EDGES}
    node_counts: Counter = Counter()
    edge_counts: Counter = Counter()
    started = time.time()

    with (
        source.open(newline="", encoding="utf-8") as src,
        (out_dir / "nodes.csv").open("w", newline="", encoding="utf-8") as nodes_file,
        (out_dir / "edges.csv").open("w", newline="", encoding="utf-8") as edges_file,
    ):
        reader = csv.reader(src)
        header = next(reader)
        column = {name: i for i, name in enumerate(header)}
        resource_columns = [
            (i, f"resource_{name}")
            for i, name in enumerate(header)
            if name.startswith(RESOURCE_PREFIXES)
        ]

        nodes = csv.writer(nodes_file)
        edges = csv.writer(edges_file)
        nodes.writerow(["id", "type"])
        edges.writerow(["src", "relation", "dst"])

        # Every resource column is a resource node, even if nobody has access (as in the paper).
        for _, resource_id in resource_columns:
            nodes.writerow([resource_id, "resource"])
        node_counts["resource"] = len(resource_columns)

        for row_number, row in enumerate(reader, start=1):
            user_id = f"user_{row[column['PERSON_ID']]}"
            nodes.writerow([user_id, "user"])
            node_counts["user"] += 1

            for relation, node_type, attribute in ATTRIBUTE_EDGES:
                node_id = f"{node_type}_{row[column[attribute]]}"
                attribute_nodes[node_type].add(node_id)
                edges.writerow([user_id, relation, node_id])
                edge_counts[relation] += 1

            for i, resource_id in resource_columns:
                if row[i] == "1":
                    edges.writerow([user_id, TARGET_RELATION, resource_id])
                    edge_counts[TARGET_RELATION] += 1

            if row_number % 5000 == 0:
                print(f"  {row_number} users ({time.time() - started:.0f}s)", flush=True)

        for node_type, node_ids in attribute_nodes.items():
            for node_id in sorted(node_ids):
                nodes.writerow([node_id, node_type])
            node_counts[node_type] = len(node_ids)

    return {"nodes": node_counts, "edges": edge_counts}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert Amazon Access Samples to nodes/edges CSV."
    )
    parser.add_argument("source", type=Path, help="amzn-anon-access-samples-2.0.csv")
    parser.add_argument("out_dir", type=Path, help="output folder for nodes.csv and edges.csv")
    args = parser.parse_args()

    counts = convert(args.source, args.out_dir)
    print("nodes:", dict(counts["nodes"]))
    print("edges:", dict(counts["edges"]))
    print(f"target relation for training: {TARGET_RELATION}")


if __name__ == "__main__":
    main()
