# Output folder:
#     embeddings.npz   one float32 matrix per node type; row i belongs to node_ids[type][i]
#     node_ids.json    node type -> list of node ids
#     metadata.json    training settings, data size, best epoch, validation loss and AUC,
#                      calibrated risk threshold ("risk_threshold")
#     history.csv      epoch, train_loss, val_loss (for the learning curve)
#     graph.json       node id -> relation -> sorted destination ids, without the target relation;
#                      read by ai-corax (pattern miner) and by OPA as data.corax.graph
#     access.json      user id -> sorted object ids of the target relation (access history);
#                      read by ai-corax only, to skip pairs that already have access
#     model.pt         trained weights, so scripts/evaluate/evaluate_hgnn.py can evaluate without training
#     split.pt         held-out test edges and the validation scores, for the same evaluation

import csv
import json
from collections import defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
import torch_geometric

from corax_hgnn.evaluate import calibrate
from corax_hgnn.graph import Graph, load_graph, read_rows
from corax_hgnn.model import HGNN
from corax_hgnn.train import TrainConfig, TrainResult


def save(
    result: TrainResult,
    graph: Graph,
    config: TrainConfig,
    out_dir: str | Path,
    data_folder: str | Path | None = None,
) -> Path:
    
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # model.pt = model weights (embedding table & SAGEConv weights), split.pt = testing + validation score
    torch.save(result.model.state_dict(), out_dir / "model.pt")
    split = {"val_labels": result.val_labels, "val_probs": result.val_probs}
    if result.test_data is not None:
        split["test_data"] = result.test_data
    torch.save(split, out_dir / "split.pt")

    # final vector for every nodes
    result.model.eval()
    with torch.no_grad():
        h = result.model.encode(graph.data)
    np.savez(out_dir / "embeddings.npz", **{t: h[t].numpy().astype(np.float32) for t in h})

    # translating row number into nodes name
    (out_dir / "node_ids.json").write_text(json.dumps(graph.node_ids, indent=2), encoding="utf-8")

    metadata = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "data": None if data_folder is None else str(data_folder),
        "target_edge_type": list(graph.target),
        "config": asdict(config),
        "best_epoch": result.best_epoch,
        "epochs_run": len(result.history),
        "best_val_loss": result.best_val_loss,
        "val_auc": result.val_auc,
        "risk_threshold": calibrate(result.val_labels, result.val_probs, config.target_pass_rate),
        "num_nodes": {t: graph.data[t].num_nodes for t in graph.data.node_types},
        "num_edges": {
            "/".join(edge_type): graph.data[edge_type].edge_index.size(1)
            for edge_type in graph.data.edge_types
        },
        "versions": {"torch": torch.__version__, "torch_geometric": torch_geometric.__version__},
    }
    (out_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    with (out_dir / "history.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["epoch", "train_loss", "val_loss"])
        writer.writerows(result.history)

    return out_dir

# saving graph structur and access log
def save_graph(data_folder: str | Path, target_relation: str, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    graph: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    access: dict[str, set[str]] = defaultdict(set)

    # read again the edges.csv then dividing the edge into 2 files because appeal rule results must be depended on the structures (not history/access log)
    for row in read_rows(Path(data_folder) / "edges.csv", ["src", "relation", "dst"]):
        if row["relation"] == target_relation:
            access[row["src"]].add(row["dst"])
        else:
            graph[row["src"]][row["relation"]].add(row["dst"])

    as_json = {
        node: {relation: sorted(dsts) for relation, dsts in sorted(relations.items())}
        for node, relations in sorted(graph.items())
    }
    path = out_dir / "graph.json"
    path.write_text(json.dumps(as_json, indent=1), encoding="utf-8")

    access_json = {user: sorted(objects) for user, objects in sorted(access.items())}
    (out_dir / "access.json").write_text(json.dumps(access_json, indent=1), encoding="utf-8")
    return path


def load_trained(out_dir: str | Path, data_folder: str | Path | None = None):
    # Rebuild a trained model from its output folder: (model, graph, split, metadata)
    out_dir = Path(out_dir)
    metadata = json.loads((out_dir / "metadata.json").read_text(encoding="utf-8"))
    data_folder = data_folder or metadata.get("data")
    if not data_folder:
        raise ValueError(f"{out_dir / 'metadata.json'} has no data folder; pass it explicitly")
    config = TrainConfig(**metadata["config"])

    graph = load_graph(data_folder, metadata["target_edge_type"][1])
    model = HGNN(graph.data, hidden=config.hidden, num_layers=config.num_layers)
    model.load_state_dict(torch.load(out_dir / "model.pt", weights_only=True))
    model.eval()
    
    split = torch.load(out_dir / "split.pt", weights_only=False)
    return model, graph, split, metadata


def load(out_dir: str | Path) -> tuple[dict[str, np.ndarray], dict[str, list[str]]]:
    out_dir = Path(out_dir)
    with np.load(out_dir / "embeddings.npz") as data:
        embeddings = {node_type: data[node_type] for node_type in data.files}
    node_ids = json.loads((out_dir / "node_ids.json").read_text(encoding="utf-8"))
    return embeddings, node_ids
