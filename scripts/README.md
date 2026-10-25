# scripts

Helpers around Corax: prepare datasets, evaluate a trained model and run the demos. None of them
trains a model, training happens only through `python -m hgnn`.

## Folders and files

| Path | Does |
|---|---|
| `prepare/` | Turns a dataset into `nodes.csv` and `edges.csv` (dummy data, Amazon, Xu & Stoller) |
| `evaluate/` | Scores a trained model: the risk score and the appeals |
| `demo_risk.py` | Shows the AI's answer next to the true one, on pairs the model never saw |
| `demo_appeal.py` | Runs three appeals end to end and lets OPA decide on the rules they write |
| `similar_cases.py` | Shows the similar cases and candidate rules for one appeal |
| `make_token.py` | Prints a demo JWT |
| `check_env.py` | Checks that the Python packages are installed |

## Run

```bash
python scripts/demo_risk.py --model-dir <model folder>
python scripts/demo_appeal.py --model-dir <model folder> --opa <path to opa>
python scripts/similar_cases.py --model-dir <model folder> --user <user> --object <object>
```

Every script and the commands for each dataset: [docs/reference.md](../docs/reference.md#scripts).
