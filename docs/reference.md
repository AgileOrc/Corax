# Reference

Details for running and configuring each part: [service API](#service-api), [policy](#policy),
[HGNN training](#hgnn-training), [scripts](#scripts) and [data format](#data-format).

## Service API

FastAPI service called by OPA and by admins. It reads the folder written by `hgnn`
(`embeddings.npz`, `node_ids.json`, `metadata.json`) and does not need torch.

| Endpoint | Caller | Does |
|---|---|---|
| `POST /risk` | OPA (`http.send`), only after the policy allowed a request | Returns `risk = 1 − σ(h_user · h_object)` from the HGNN embeddings |
| `GET /health` | Checks, demo | Model info: target edge type, risk threshold, number of users and objects |
| `POST /corax/appeals` | Admin, through Envoy and OPA | Writes the exact exception at once, returns similar cases and candidate patterns |
| `GET /corax/appeals/{id}` | Admin | The appeal record and its history (audit log) |
| `POST /corax/appeals/{id}/confirm` | Admin | Writes the rule the admin accepted as a validated rule, or keeps only the exception |

Concepts: [Risk score](how-it-works.md#risk-score), [Appeal path](how-it-works.md#appeal-path).

### Run

```
pip install -r service/requirements.txt
CORAX_MODEL_DIR=output/exp-hard50 uvicorn main:app --app-dir service --port 8000
```

| Variable | Default | Meaning |
|---|---|---|
| `CORAX_MODEL_DIR` | `output/hgnn` | Folder written by `hgnn` |
| `AI_RISK_THRESHOLD` | `risk_threshold.value` in `metadata.json` | Optional override |
| `GENERATED_DIR` | `policies/generated` | Where validated Rego files are written (OPA loads it with `--watch`) |
| `APPEALS_DIR` | `appeals` | One JSON record per appeal, with its history |
| `CORAX_CONFIG` | none | The application's `data.json` (the one OPA loads). Its `corax.config.jwt` and `corax.config.admin.users` are used to verify admins. Without it the appeal endpoints return 503 response code |
| `OPA_PATH` | `opa` | OPA binary used to validate generated files |
| `POLICY_DIR` | none | The application's policy folder. Its `opa test` must still pass |
| `OBJECT_IDENTITY` | `false` | Allow "object is <id>" in candidates (objects that are systems, as in the Amazon data) |
| `APPEAL_CANDIDATES` | `8` | How many candidate patterns an appeal returns |
| `AUTO_APPLY_MAX_USER_SHARE` | `0.4` | Share of all users (0 to 1, e.g. `0.5` = 50%) that may get new access. Above it a rule is "large" |
| `AUTO_APPLY_MAX_PAIRS`, `AUTO_APPLY_MAX_MEAN_RISK` | `50`, `0.5` | New (user, object) pairs and their mean risk. Above either a rule is "large" |

A large rule needs `acknowledge_scope`. No regulation fixes these numbers (ISO 27001, NIST 800-53 and PCI DSS ask that access grants are approved and logged, not for a size limit). Set them to the organization's risk appetite. `AUTO_APPLY_MAX_USER_SHARE=0` makes every rule wait for an admin.

Appeals need `graph.json` and `access.json` in the model folder. Without them only `/risk` runs.

### `POST /risk`

```json
{"user": "user_0", "object": "resource_HOST_100"}
```

```json
{"risk": 0.0123, "high_risk": false, "threshold": 0.978, "reason": null}
```

- `high_risk` is true when `risk > threshold`. OPA only reads `high_risk`.
- If the user or object has no embedding, `risk` is `null`, `high_risk` is false and `reason`
  says which one is unknown. The policy decision stands.
- The service has no authentication. It must only be reachable by OPA (internal network).

### Appeals

```
POST /corax/appeals                {"user": "alice", "object": "report_105", "action": "read_report", "reason": "..."}
  → 201 {"id": "appeal-0001", "status": "exception_applied", "neighbours": [...],
         "candidates": [{"index": 1, "pattern": "...", "users": 3, "pairs": 12, "support": 0.6, ...}, ...]}

POST /corax/appeals/appeal-0001/confirm   {"candidate": 3, "acknowledge_scope": false}
  → 200 {"status": "rule_applied", "chosen": {...scope, tier...}, "validation": [...]}
  → 409 when the rule is large and acknowledge_scope is false (the scope is in the response)
  → 422 when the rule fails validation (nothing is written)
POST /corax/appeals/appeal-0001/confirm   {"candidate": null}
  → 200 {"status": "exception_only"}
```

- The exception (`<id>-exception.rego`) is written as soon as the appeal is created, the rule
  (`<id>-rule.rego`) only after the admin accepts one of the proposed rules. Both are validated with opa first and
  written atomically, so OPA never loads half a file.
- An appeal is confirmed once.
- Candidates skip values that are too specific to the appealed pair: a value both the user and the
  object have (the `user.X = object.Y` candidate covers it for every value), and a value of an
  attribute with several values (e.g. one of the projects a user works on). Otherwise one slice per
  value would rank above the general rule, because it opens fewer pairs.

### Admin authentication

Every appeal endpoint needs `Authorization: Bearer <JWT>` of an admin. corax-service checks it itself,
even though OPA already did, so calling corax-service directly does not bypass the check:

| Check | Result |
|---|---|
| No token, not `Bearer`, bad signature, expired, wrong `iss` / `aud`, no `exp` or `sub` | 401 |
| Valid token, `sub` not in `corax.config.admin.users` | 403 |
| `CORAX_CONFIG` not set or has no `corax.config.jwt` | 503 (fails closed) |

- Key, issuer, audience and admin list come from the same `data.json` as OPA, re-read when the
  file changes, so both always agree.
- `secret` allows only HS256, `cert` (a PEM public key) allows only RS256 / ES256. With a public
  key corax-service can verify tokens but never create them.
- The `x-corax-user` header is ignored. The audit log records the `sub` of the verified token.
- `/risk` has no authentication and must stay on the internal network, reachable only by OPA.

## Policy

Generic Rego framework shared by every application that uses Corax (package `corax.authz`).

```
Envoy ext_authz input
  1. verify the JWT                      → user.id = sub
  2. match method + path to a route      → action, resource {type, id, ...}
  3. admin_allow     = corax.* action AND user in config.admin.users   (Corax admin routes)
     exception_allow = data.app.exceptions.allow  (the exact pair an admin approved in an appeal)
     policy_allow    = data.app.authz.allow       (the application's rules)
                    OR data.app.generated.allow   (rules added through appeals)
  4. ai_high_risk = POST corax-service /risk            (only when policy_allow and not an exception)
  5. allow = admin_allow OR exception_allow OR (policy_allow AND NOT ai_high_risk)
```

| File | Content |
|---|---|
| `request.rego` | JWT verification, route matching, the normalized `request` |
| `authz.rego` | `allow`, the AI risk check, `reason`, and `result` for opa-envoy-plugin |
| `authz_test.rego` | Tests, with corax-service and the application's rules mocked |
| `config.example.json` | Example configuration |

### What an application provides

**1. Rules** in package `app.authz` that define `allow`. Their `input` is the normalized request,
never the raw Envoy input:

```json
{
  "user": {"id": "alice"},
  "action": "read_report",
  "resource": {"type": "report", "id": "report_105", "quarter": "Q3"}
}
```

Appeals write two kinds of files to `policies/generated/`, both defining `allow`:

| Package | Content | AI risk check |
|---|---|---|
| `app.exceptions` | Only the exact (user, action, object) the admin approved | Skipped: the admin reviewed it |
| `app.generated` | The broader rule mined from similar cases | Yes |

**2. Configuration** under `data.corax.config` (see `config.example.json`):

| Key | Meaning |
|---|---|
| `jwt` | Constraints for `io.jwt.decode_verify`: `secret` (HS256, demo) or `cert` (JWKS / PEM, production), plus `iss` and `aud`. `exp` and `nbf` are always checked |
| `routes` | `method`, `path` with `:name` parameters, `action`, `resource_type`. Exactly one route must match, otherwise the request is denied. The `:id` parameter is the object sent to corax-service |
| `ai.url`, `ai.timeout` | corax-service address and `http.send` timeout (default `20ms`). Without `ai`, no risk check is made |
| `admin.users` | User ids (JWT `sub`) allowed to use the Corax admin routes. Without it, nobody is an admin |

**3. Graph data:** `hgnn` writes `graph.json` (node id → relation → destination ids).
Generated rules read it as `data.corax.graph`, so copy it to `<policy folder>/corax/graph/data.json`.
OPA places data files by folder and merges it with `data.corax.config`.

### Admin routes

Corax adds these routes itself, applications do not list them in `config.routes`. They are served
by corax-service, so Envoy routes `/corax/` there.

| Method and path | Action |
|---|---|
| `POST /corax/appeals` | `corax.appeal.create` |
| `GET /corax/appeals/:id` | `corax.appeal.read` |
| `POST /corax/appeals/:id/confirm` | `corax.appeal.confirm` |

Only `config.admin.users` may call them. For `corax.*` actions the application's rules, appeal
rules and exceptions are ignored, so no generated rule can make someone an admin. Admin actions do
not call the AI risk check.

### Guarantees

- Identity comes only from a verified JWT (`sub`). The resource comes only from the URL path, the query string and body are ignored.
- The AI is asked only after the policy allowed the request, so it can only deny.
- If corax-service errors, times out, or does not know the user or object, the policy decision stands (`reason`: `allowed without AI check`).
- Rules from appeals also go through the AI risk check. Only the exact pair an admin approved skips it.
- Only listed admins can create or confirm appeals, and no rule can grant that.
- An allowed request carries the verified user id to the upstream service in `x-corax-user` (set by Envoy from `result.headers`). corax-service does not rely on it: it verifies the admin's JWT itself.

### Entry points

| Path | Value |
|---|---|
| `corax/authz/allow` | boolean |
| `corax/authz/result` | `{"allowed": bool, "headers": {"x-corax-user": "..."}, "dynamic_metadata": {"corax_reason": "...", "corax_risk": 0.12}}`, for opa-envoy-plugin and Envoy access logs |

### Test

```
opa check --strict policy
opa test policy -v
```

## HGNN training

Trains the heterogeneous GraphSAGE model (implementation of the method in [[1]](evaluation.md#references)) and exports one embedding per node.

| File | Does |
|---|---|
| `graph.py` | Loads `nodes.csv` / `edges.csv` into a PyTorch Geometric `HeteroData` |
| `model.py` | Learnable node embeddings, 2 × SAGEConv + ReLU, `to_hetero`, dot-product decoder |
| `train.py` | Link prediction training with early stopping, validation AUC |
| `export.py` | Saves and loads embeddings and training metadata |
| `__main__.py` | Command-line entry point: `python -m hgnn` |

Input format: [Data format](#data-format)</br> Concepts: [Risk score](how-it-works.md#risk-score)

### Usage

From the repository root:

```bash
python -m hgnn --data tests/hgnn/fixtures/toy_graph --target-relation accessed --out output/toy
python scripts/evaluate/evaluate_hgnn.py --model-dir output/toy
```

Training runs once, then `evaluate_hgnn.py` loads the saved model and scores it on the held-out test edges.

Options (defaults follow the paper): `--hidden 64`, `--num-layers 2`, `--learning-rate 0.001`,
`--max-epochs 1000`, `--patience 10`, `--seed 0`. Not from the paper: `--test-ratio 0.1` (80/10/10
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

Every dataset follows the same flow. [Getting started](getting-started.md) walks through it on the dummy data.

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
| `demo_appeal.py` | Demo on the dummy data: three appeals (small rule written, large rule refused with 409, exception only) end to end, then opa evaluates the written Rego. Nothing is trained |
| `make_token.py` | Prints a demo JWT signed with the HS256 secret of a Corax config (`deploy/demo/data.json` by default) |
| `demo_risk.py` | Demo: the risk score on held-out pairs the model never saw, next to the true answer. Nothing is trained or written |
| `similar_cases.py` | For one appealed (user, object) pair: the kNN similar cases, the candidate patterns and, with `--pick N`, the tier, Rego and validation of candidate N. Nothing is written |
| `prepare/make_dummy.py` | Writes the small dummy data graph with two appeal scenarios, for tests and local trials |
| `prepare/convert_amazon.py` | Converts the UCI Amazon Access Samples dataset (CC BY 4.0) |
| `prepare/make_amazon_scenarios.py` | Hides inferred role-based rules (title → resource) in the Amazon graph, for evaluating appeals |
| `prepare/convert_xu_stoller.py` | Converts a Xu & Stoller ABAC policy (`.abac`) with one rule hidden (`--hide-rule N`) or each rule in turn (`--all-rules`) |
| `prepare/appeal_scenarios.py` | Reads and writes `scenarios.json` (used by the scripts above) |
| `evaluate/evaluate_hgnn.py` | Test metrics of the risk score and the risk threshold calibration table |
| `evaluate/evaluate_knn.py` | kNN precision@k, rank of the hidden rule among the candidate patterns, and its tier |

### Dummy data

```bash
python scripts/prepare/make_dummy.py output/dummy-data
python -m hgnn --data output/dummy-data --target-relation accessed --out output/dummy --learning-rate 0.01 --patience 50
python scripts/demo_risk.py --model-dir output/dummy
python scripts/demo_appeal.py --model-dir output/dummy --opa path/to/opa
python scripts/evaluate/evaluate_knn.py --model-dir output/dummy --scenarios output/dummy-data/scenarios.json
python scripts/similar_cases.py --model-dir output/dummy --user lecturer_head_P0 --object student_P0_05
```

The candidate "user.member_of = object.member_of AND user holds position_head_of_program" should be
among the first few.

### Amazon dataset

1. Download `amzn-anon-access-samples-2.0.csv` from
   [UCI](https://archive.ics.uci.edu/dataset/216/amazon+access+samples) into `datasets/` (git-ignored, about 4.8 GB).
2. Convert (about 1 minute):

   ```bash
   python scripts/prepare/convert_amazon.py datasets/amzn-anon-access-samples-2.0.csv datasets/amazon-graph
   ```

   Expected: 36,063 users, 33,252 resources, 405 departments, 4,979 titles, 3,207 managers,
   595,506 `has_potential_access` edges.
3. Risk score: train once (80/10/10), then evaluate the saved model:

   ```bash
   python -m hgnn --data datasets/amazon-graph --target-relation has_potential_access --hard-negative-ratio 0.5 --out output/exp-hard50
   python scripts/evaluate/evaluate_hgnn.py --model-dir output/exp-hard50
   ```

4. Appeals: hide 10 inferred rules "title T gets resource R" (413 access edges) plus 2 one-off appeals.
   One training run covers all of them.

   ```bash
   python scripts/prepare/make_amazon_scenarios.py datasets/amazon-graph datasets/amazon-appeals
   python -m hgnn --data datasets/amazon-appeals --target-relation has_potential_access --out output/amazon-appeals
   python scripts/evaluate/evaluate_knn.py --model-dir output/amazon-appeals --scenarios datasets/amazon-appeals/scenarios.json
   ```

### Xu & Stoller ABAC policies

Standard policy mining benchmark [[6]](evaluation.md#references). Download `ABAC-Mining.zip` from Stoller's
[software page](https://www3.cs.stonybrook.edu/~stoller/software/) into `datasets/xu-stoller/` and
extract the `.abac` files there. The archive is GPL-3.0: keep it under `datasets/` (git-ignored). The
scripts here only read the format.

Each rule is hidden in turn: the pairs only that rule grants are removed from the access edges, so every
rule gives its own data folder and its own model. Candidates use up to 3 predicates and `object has ...`
(the resource type matters in every rule). Rule 3 of the university policy is skipped: rule 2 already
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
| `id` | Unique node id across the whole file, e.g. `alice` |
| `type` | Node type, e.g. `employee`, `report`, `department` |

```csv
id,type
alice,employee
report_105,report
department_sales,department
```

### edges.csv

| Column | Meaning |
|---|---|
| `src` | Source node id (must exist in `nodes.csv`) |
| `relation` | Relation name, e.g. `works_on`, `member_of` |
| `dst` | Destination node id (must exist in `nodes.csv`) |

```csv
src,relation,dst
alice,member_of,department_sales
alice,accessed,report_105
```

The edge type is the triple `(source type, relation, destination type)`, derived from the node types.
The same relation name may connect different node types, e.g. `(employee, member_of, department)` and
`(report, member_of, department)` are two edge types.

### Rules

- Every node type must appear in at least one edge.
- One relation is the **target relation** for link prediction (passed as `--target-relation`).
  It must connect exactly one pair of node types, e.g. `accessed` from `employee` to `report`.
  Its edges should come only from requests the policy allowed.
- Extra columns are allowed and ignored by the HGNN.

### scenarios.json (appeal evaluation only)

Optional. Only `scripts/evaluate/evaluate_knn.py` reads it, training and the running service do not.
Each scenario is an appeal with a known answer: the pairs of a rule that was removed from the access
edges (`hidden/<name>.csv`), and the predicates of that rule.

```json
{
  "target_relation": "accessed",
  "object_identity": false,
  "object_values": false,
  "max_size": 2,
  "scenarios": [
    {
      "name": "manager",
      "appeal": ["alice", "report_105"],
      "expected": [
        {"kind": "shared", "relation": "member_of", "other": "member_of"},
        {"kind": "user_has", "relation": "holds", "other": "role_manager"}
      ],
      "hidden": "hidden/manager.csv"
    },
    {"name": "one_off", "appeal": ["bob", "report_731"], "expected": null, "hidden": null}
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
