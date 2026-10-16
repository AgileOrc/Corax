# hgnn-job

Trains the heterogeneous GraphSAGE model (reimplementation of Yin et al. 2024) and exports one embedding per node.

| File | Does |
|---|---|
| `corax_hgnn/graph.py` | Loads `nodes.csv` / `edges.csv` into a PyTorch Geometric `HeteroData` |
| `corax_hgnn/model.py` | Learnable node embeddings, 2 × SAGEConv + ReLU, `to_hetero`, dot-product decoder |
| `corax_hgnn/train.py` | Link prediction training with early stopping, validation AUC |
| `corax_hgnn/export.py` | Saves and loads embeddings and training metadata |
| `run.py` | Command-line entry point |

Input format: [docs/data-format.md](../docs/data-format.md).

## Usage

From the repository root:

```bash
python hgnn-job/run.py --data tests/hgnn/fixtures/toy_graph --target-relation accessed --out output/toy
```

Options (defaults follow the paper): `--hidden 64`, `--learning-rate 0.001`, `--max-epochs 1000`,
`--patience 10`, `--seed 0`.

## Output

| File | Content |
|---|---|
| `embeddings.npz` | One float32 matrix per node type; row *i* belongs to `node_ids[type][i]` |
| `node_ids.json` | Node type → list of node ids |
| `metadata.json` | Settings, data size, best epoch, validation loss and AUC, library versions |
| `history.csv` | `epoch,train_loss,val_loss` for the learning curve |
