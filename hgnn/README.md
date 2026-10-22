# hgnn

Trains the heterogeneous GraphSAGE model (reimplementation of Yin et al. 2024) and exports one embedding per node.

| File | Does |
|---|---|
| `graph.py` | Loads `nodes.csv` / `edges.csv` into a PyTorch Geometric `HeteroData` |
| `model.py` | Learnable node embeddings, 2 × SAGEConv + ReLU, `to_hetero`, dot-product decoder |
| `train.py` | Link prediction training with early stopping, validation AUC |
| `export.py` | Saves and loads embeddings and training metadata |
| `__main__.py` | Command-line entry point: `python -m hgnn` |

Input format: [docs/data-format.md](../docs/data-format.md).

## Usage

From the repository root:

```bash
python -m hgnn --data tests/hgnn/fixtures/toy_graph --target-relation accessed --out output/toy
python scripts/evaluate/evaluate_hgnn.py --model-dir output/toy
```

Training runs once; `evaluate_hgnn.py` loads the saved model and scores it on the held-out test edges.

Options (defaults follow the paper): `--hidden 64`, `--num-layers 2`, `--learning-rate 0.001`,
`--max-epochs 1000`, `--patience 10`, `--seed 0`. Not from the paper: `--test-ratio 0.1` (80/10/10
split; 0 = no test set), `--hard-negative-ratio 0` (0.5 worked best on Amazon), `--target-pass-rate 0.99`
(sets the exported risk threshold).

## Output

| File | Content |
|---|---|
| `embeddings.npz` | One float32 matrix per node type; row *i* belongs to `node_ids[type][i]` |
| `node_ids.json` | Node type → list of node ids |
| `metadata.json` | Settings, data size, best epoch, validation loss and AUC, calibrated `risk_threshold`, library versions |
| `history.csv` | `epoch,train_loss,val_loss` for the learning curve |
| `graph.json` | Node id → relation → destination ids, without the target relation. Read by corax-service and loaded by OPA as `data.corax.graph` |
| `access.json` | User id → object ids of the target relation (access history). Read by corax-service only, to skip pairs that already have access |
| `model.pt` | Trained weights, for `scripts/evaluate/evaluate_hgnn.py` |
| `split.pt` | Held-out test edges and validation scores, for `scripts/evaluate/evaluate_hgnn.py` |
