# hgnn-job

Trains the heterogeneous GraphSAGE model (reimplementation of Yin et al. 2024) and exports one embedding per node.

| File | Status | Does |
|---|---|---|
| `corax_hgnn/graph.py` | done | Loads `nodes.csv` / `edges.csv` into a PyTorch Geometric `HeteroData` |
| `corax_hgnn/model.py` | planned | Learnable node embeddings, 2 × SAGEConv + ReLU, `to_hetero`, dot-product decoder |
| `corax_hgnn/train.py` | planned | Link prediction training with early stopping |
| `corax_hgnn/export.py` | planned | Saves embeddings and training metadata to `output/` |
| `run.py` | planned | Command-line entry point |

Input format: [docs/data-format.md](../docs/data-format.md).
