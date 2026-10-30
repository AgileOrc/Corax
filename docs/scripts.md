# Scripts

How to prepare data, train the model, evaluate it and run the demo scripts without Docker. Run every
command from the repository root.

## HGNN training

Trains the heterogeneous GraphSAGE model (implementation of the method in [[1]](references.md)) and exports one embedding per node.

| File | Does |
|---|---|
| `graph.py` | Loads `nodes.csv` / `edges.csv` into a PyTorch Geometric `HeteroData` |
| `model.py` | Learnable node embeddings, 2 × SAGEConv + ReLU, `to_hetero`, dot-product decoder |
| `train.py` | Link prediction training with early stopping, validation AUC |
| `export.py` | Saves and loads embeddings and training metadata |
| `__main__.py` | Command-line entry point: `python -m hgnn` |

The input format is in [Data format](#data-format), and the concepts are in [Risk score](ai-model-and-evaluation.md#risk-score).

### Usage

From the repository root:

```bash
python -m hgnn --data tests/hgnn/fixtures/toy_graph --target-relation accessed --out output/toy
python scripts/evaluate/evaluate_hgnn.py --model-dir output/toy
```

Training runs once, then `evaluate_hgnn.py` loads the saved model and scores it on the held-out test edges.

The defaults of `--hidden 64`, `--num-layers 2`, `--learning-rate 0.001`, `--max-epochs 1000`,
`--patience 10` and `--seed 0` follow [Yin et al.](references.md). Corax adds `--test-ratio 0.1` (80/10/10
split, 0 = no test set), `--hard-negative-ratio 0` (0.5 worked best on Amazon), `--target-pass-rate 0.99`
(sets the exported risk threshold).

### Output

| File | Content |
|---|---|
| `embeddings.npz` | One float32 matrix per node type, row *i* belongs to `node_ids[type][i]` |
| `node_ids.json` | Node type → list of node ids |
| `metadata.json` | Settings, data size, best epoch, validation loss and AUC, calibrated `risk_threshold`, library versions |
| `history.csv` | `epoch,train_loss,val_loss` for the learning curve |
| `graph.json` | Node id → relation → destination ids, without the target relation. Read by corax-service and loaded by OPA as `data.corax.graph` |
| `access.json` | User id → object ids of the target relation (access history). Read by corax-service only, to skip pairs that already have access |
| `model.pt` | Trained weights, for `scripts/evaluate/evaluate_hgnn.py` |
| `split.pt` | Held-out test edges and validation scores, for `scripts/evaluate/evaluate_hgnn.py` |

## Scripts

These docs use one dataset throughout, the demo company that `prepare` generates for the Docker demo ([Getting started](getting-started.md#deploy-with-docker)). Every dataset follows the same flow.

```
prepare/   dataset → nodes.csv, edges.csv, scenarios.json, hidden/*.csv   (see Data format)   
   │
python -m hgnn   trains the HGNN once and saves the model folder           (the only place that trains)
   │
evaluate/  loads the saved model, never trains
```

| Script | Does |
|---|---|
| `check_env.py` | Checks that the Python environment has the required packages |
| `demo_risk.py` | Demo: the risk score on held-out pairs the model never saw, next to the true answer. Nothing is trained or written |
| `similar_cases.py` | For one appealed (user, object) pair: the kNN similar cases, the candidate patterns and, with `--pick N`, the tier, Rego and validation of candidate N. Nothing is written |
| `prepare/convert_amazon.py` | Converts the UCI Amazon Access Samples dataset (CC BY 4.0) |
| `prepare/make_amazon_scenarios.py` | Hides inferred role-based rules (title → resource) in the Amazon graph, for evaluating appeals |
| `prepare/convert_xu_stoller.py` | Converts a Xu & Stoller ABAC policy (`.abac`) with one rule hidden (`--hide-rule N`) or each rule in turn (`--all-rules`) |
| `prepare/appeal_scenarios.py` | Reads and writes `scenarios.json` (used by the scripts above) |
| `prepare/make_enterprise.py`, `prepare/make_office.py` | The synthetic enterprise and office graphs of the document app demo ([scripts/README.md](../scripts/README.md)) |
| `demo_gateway.py`, `demo_office.py`, `demo_office_cases.py`, `demo_backend.py` | The document app demo: prepare its graph and model, then send its cases through the Docker gateway ([docs/demo.md](demo.md)) |
| `evaluate/evaluate_hgnn.py` | Test metrics of the risk score and the risk threshold calibration table |
| `evaluate/evaluate_knn.py` | kNN precision@k, rank of the hidden rule among the candidate patterns, and its tier |
| `prepare/make_dummy.py`, `demo_appeal.py` | A small dummy graph and three appeals on it, for the tests and for development ([Small test data](#small-test-data)) |

### Small test data

The tests use a small dummy graph, because it trains in seconds. You do not need it to try Corax.

```bash
python scripts/prepare/make_dummy.py output/dummy-data
python -m hgnn --data output/dummy-data --target-relation accessed --out output/dummy --learning-rate 0.01 --patience 50
python scripts/demo_appeal.py --model-dir output/dummy --opa path/to/opa
```

`demo_appeal.py` runs three appeals on it end to end, a narrow rule, a broad rule and an exception only, and
then lets OPA decide on the Rego it wrote.

### Amazon dataset

1. Download `amzn-anon-access-samples-2.0.csv` from
   [UCI](https://archive.ics.uci.edu/dataset/216/amazon+access+samples) into `datasets/` (git-ignored, about 4.8 GB).
2. Convert (about 1 minute):

   ```bash
   python scripts/prepare/convert_amazon.py datasets/amzn-anon-access-samples-2.0.csv datasets/amazon-graph
   ```

   You should get 36,063 users, 33,252 resources, 405 departments, 4,979 titles, 3,207 managers,
   595,506 `has_potential_access` edges.
3. For the risk score, train once (80/10/10), then evaluate the saved model.

   ```bash
   python -m hgnn --data datasets/amazon-graph --target-relation has_potential_access --hard-negative-ratio 0.5 --out output/exp-hard50
   python scripts/evaluate/evaluate_hgnn.py --model-dir output/exp-hard50
   ```

4. For the appeals, hide 10 inferred rules "title T gets resource R" (413 access edges) plus 2 one-off appeals.
   One training run covers all of them.

   ```bash
   python scripts/prepare/make_amazon_scenarios.py datasets/amazon-graph datasets/amazon-appeals
   python -m hgnn --data datasets/amazon-appeals --target-relation has_potential_access --out output/amazon-appeals
   python scripts/evaluate/evaluate_knn.py --model-dir output/amazon-appeals --scenarios datasets/amazon-appeals/scenarios.json
   ```

### Xu & Stoller ABAC policies

Standard policy mining benchmark [[6]](references.md). Download `ABAC-Mining.zip` from Stoller's
[software page](https://www3.cs.stonybrook.edu/~stoller/software/) into `datasets/xu-stoller/` and
extract the `.abac` files there. The archive is GPL-3.0, so keep it under `datasets/` (git-ignored). The
scripts here only read the format.

Each rule is hidden in turn. The pairs only that rule grants are removed from the access edges, so every
rule gives its own data folder and its own model. Candidates use up to 3 predicates and `object has ...`
(the resource type matters in every rule). Rule 3 of the university policy is skipped, because rule 2 already
grants all its pairs.

```bash
# 1. prepare: output/xu-stoller/<file>/rule_NN/data
for f in datasets/xu-stoller/ABACMining/gen-case-studies/university/university-sets_10_*.abac; do python scripts/prepare/convert_xu_stoller.py "$f" "output/xu-stoller/$(basename "$f" .abac)" --all-rules; done
# 2. train each once: output/xu-stoller/<file>/rule_NN/model (about 5 seconds each)
for d in output/xu-stoller/*/rule_*; do python -m hgnn --data "$d/data" --target-relation accessed --out "$d/model" --learning-rate 0.01 --patience 50 --test-ratio 0; done
# 3. evaluate the saved models (no training)
python scripts/evaluate/evaluate_knn.py --runs "output/xu-stoller/*/rule_*" --out output/xu-stoller/results.json
```

The `ir-gen-case-studies` folder holds the same policies with irrelevant attributes added, for a noise test.

## Data format

Corax does not know about any specific domain. Any application (a company, a hospital, a shop)
describes its users, objects and relations as a typed graph in two CSV files.

### nodes.csv

| Column | Meaning |
|---|---|
| `id` | Unique node id across the whole file, e.g. `employee_E049` |
| `type` | Node type, e.g. `employee`, `document`, `department` |

```csv
id,type
employee_E049,employee
document_D057,document
department_engineering,department
```

### edges.csv

| Column | Meaning |
|---|---|
| `src` | Source node id (must exist in `nodes.csv`) |
| `relation` | Relation name, e.g. `works_in`, `owned_by` |
| `dst` | Destination node id (must exist in `nodes.csv`) |

```csv
src,relation,dst
employee_E049,works_in,department_engineering
document_D057,owned_by,department_engineering
employee_E040,accessed,document_D033
```

The edge type is the triple `(source type, relation, destination type)`, derived from the node types.
The same relation name may connect different node types, e.g. `(employee, member_of, team)` and
`(document, member_of, team)` would be two edge types.

### Rules

- Every node type must appear in at least one edge.
- One relation is the **target relation** for link prediction (passed as `--target-relation`).
  It must connect exactly one pair of node types, e.g. `accessed` from `employee` to `document`.
  Its edges should come only from requests the policy allowed.
- Extra columns are allowed and ignored by the HGNN.

### scenarios.json (appeal evaluation only)

Optional. Only `scripts/evaluate/evaluate_knn.py` reads it, training and the running service do not.
Each scenario is an appeal with a known answer, which is the pairs of a rule that was removed from the access
edges (`hidden/<name>.csv`), and the predicates of that rule.

```json
{
  "target_relation": "accessed",
  "object_identity": false,
  "object_values": false,
  "max_size": 2,
  "scenarios": [
    {
      "name": "coordinator",
      "appeal": ["employee_E049", "document_D057"],
      "expected": [
        {"kind": "shared", "relation": "works_in", "other": "owned_by"},
        {"kind": "user_has", "relation": "holds", "other": "role_coordinator"}
      ],
      "hidden": "hidden/coordinator.csv"
    },
    {"name": "one_off", "appeal": ["employee_E040", "document_D037"], "expected": null, "hidden": null}
  ]
}
```

| Field | Meaning |
|---|---|
| `target_relation` | Same as `--target-relation` for training |
| `object_identity`, `object_values`, `max_size` | Candidate options: allow `object is <id>`, allow `object has <value>`, max predicates per candidate (defaults `false`, `false`, `2`) |
| `appeal` | The (user, object) pair that is appealed. It must not be in the access edges |
| `expected` | Predicates of the hidden rule (kinds: `user_has`, `object_has`, `shared`, `direct`, `object_is`), or `null` for a one-off appeal from which nothing should be generalized |
| `hidden` | CSV with `user,object` rows: every pair the hidden rule grants and the access edges leave out, or `null` |

The data folder then looks like:

```
nodes.csv
edges.csv
scenarios.json
hidden/manager.csv
```
## The demo company without Docker

The Docker demo is the way to see Corax. These scripts look inside the same model from the host, without the
gateway. Run `prepare` first ([Getting started](getting-started.md#deploy-with-docker)). It writes the demo
company to `output/gateway/data` and its model to `output/gateway/hgnn`, and the scripts read both.

### The AI on access it has never seen

```bash
python scripts/demo_risk.py --model-dir output/gateway/hgnn
```

The script scores pairs from the test split, which training never saw, and puts the true answer next to the AI's.

| Row | Meaning | The AI should |
|---|---|---|
| **allowed** | A real access the model never saw | Let it pass |
| **not allowed** | A random pair without access | Deny it |
| **peer has it** | A pair without access, but a peer of the user has the object. It looks normal, the hardest case | Deny it |

A pair is denied when its risk is above the threshold, the same rule `/risk` uses. In the real flow the AI only
sees requests the rules already allowed. The "not allowed" rows show what it would catch if a wrong or
over-broad rule let such a request through. A miss there means the AI adds no deny, and the rules' decision
stands.

### One appeal, step by step

Chloe's request from the demo, with its similar cases, the candidate rules, and the tier, Rego and validation of
the first one. Nothing is written.

```bash
python scripts/similar_cases.py --model-dir output/gateway/hgnn --user employee_E049 --object document_D057 --pick 1
```

The validation needs the [OPA binary](https://www.openpolicyagent.org/docs/latest/#running-opa). Without it, the script
shows everything else and says the validation was skipped. Pass `--opa path/to/opa` if it is not on the `PATH`.

How appeals work is in [Appeal path](ai-model-and-evaluation.md#appeal-path).

### The risk endpoint as OPA calls it

```bash
CORAX_MODEL_DIR=output/gateway/hgnn uvicorn main:app --app-dir service --port 8000
```

```bash
curl -X POST localhost:8000/risk -H "Content-Type: application/json" -d '{"user": "employee_E049", "object": "document_D057"}'
```

The answer has the risk, whether it is above the threshold, and the threshold. Every user and object id is in
`output/gateway/hgnn/node_ids.json`. `/risk` uses the embeddings of the whole graph, so its numbers differ
slightly from `demo_risk.py`, which recomputes them without the test edges.

### Larger datasets

The same flow (prepare, `python -m hgnn`, evaluate) runs on the Amazon Access Samples dataset and the
Xu & Stoller ABAC policies. Read [scripts](scripts.md#scripts) and [evaluation](ai-model-and-evaluation.md#evaluation).
