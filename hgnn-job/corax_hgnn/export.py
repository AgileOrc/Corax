"""Save and load the trained node embeddings.

Output folder:
    embeddings.npz   one float32 matrix per node type; row i belongs to node_ids[type][i]
    node_ids.json    node type -> list of node ids
    metadata.json    training settings, data size, best epoch, validation loss and AUC
    history.csv      epoch, train_loss, val_loss (for the learning curve)
"""

import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch
import torch_geometric

from corax_hgnn.graph import Graph
from corax_hgnn.train import TrainConfig, TrainResult


def save(result: TrainResult, graph: Graph, config: TrainConfig, out_dir: str | Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Final embeddings use the full graph, including every target edge as a message.
    result.model.eval()
    with torch.no_grad():
        h = result.model.encode(graph.data)
    np.savez(out_dir / "embeddings.npz", **{t: h[t].numpy().astype(np.float32) for t in h})

    (out_dir / "node_ids.json").write_text(json.dumps(graph.node_ids, indent=2), encoding="utf-8")

    metadata = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "target_edge_type": list(graph.target),
        "config": asdict(config),
        "best_epoch": result.best_epoch,
        "epochs_run": len(result.history),
        "best_val_loss": result.best_val_loss,
        "val_auc": result.val_auc,
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


def load(out_dir: str | Path) -> tuple[dict[str, np.ndarray], dict[str, list[str]]]:
    """Return (embeddings per node type, node ids per node type)."""
    out_dir = Path(out_dir)
    with np.load(out_dir / "embeddings.npz") as data:
        embeddings = {node_type: data[node_type] for node_type in data.files}
    node_ids = json.loads((out_dir / "node_ids.json").read_text(encoding="utf-8"))
    return embeddings, node_ids
