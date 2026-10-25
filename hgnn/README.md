# hgnn

The graph model behind Corax's AI. It trains on the access graph (users, objects and how they are
related) and writes one vector per node, which the service uses for the risk score and for finding
similar cases in appeals. The method follows [[1]](../docs/evaluation.md#references).

## Files

| File | Does |
|---|---|
| `graph.py` | Reads `nodes.csv` and `edges.csv` into a typed graph |
| `model.py` | The model: two GraphSAGE layers and a dot product between a user and an object |
| `train.py` | Training: learns to predict past access, stops early, calibrates the risk threshold |
| `evaluate.py` | Scores a trained model on the held-out test edges |
| `peers.py` | Finds peers of a user, used for hard negatives and evaluation |
| `export.py` | Writes and reads the model folder |
| `__main__.py` | The command `python -m hgnn` |

## Run

From the repository root:

```bash
python -m hgnn --data <data folder> --target-relation accessed --out <model folder>
```

Input format, options and the files written: [docs/reference.md](../docs/reference.md#hgnn-training).
