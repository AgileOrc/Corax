# ai-corax

FastAPI service called by OPA and by admins. It reads the folder written by `hgnn-job`
(`embeddings.npz`, `node_ids.json`, `metadata.json`) and does not need torch.

| Endpoint | Caller | Does | Status |
|---|---|---|---|
| `POST /risk` | OPA (`http.send`), only after the policy allowed a request | Returns `risk = 1 − σ(h_user · h_object)` from the HGNN embeddings | Built |
| `GET /health` | Checks, demo | Model info: target edge type, risk threshold, number of users and objects | Built |
| `POST /corax/appeals` | Admin, through Envoy and OPA | Writes the exact exception at once, returns similar cases and candidate patterns | Built |
| `GET /corax/appeals/{id}` | Admin | The appeal record and its history (audit log) | Built |
| `POST /corax/appeals/{id}/confirm` | Admin | Writes the chosen candidate as a validated rule, or keeps only the exception | Built |

See [docs/ai-design.md](../docs/ai-design.md), sections 2, 4–7.

## Run

```
pip install -r ai-corax/requirements.txt
CORAX_MODEL_DIR=output/exp-hard50 uvicorn main:app --app-dir ai-corax --port 8000
```

| Variable | Default | Meaning |
|---|---|---|
| `CORAX_MODEL_DIR` | `output/hgnn` | Folder written by `hgnn-job` |
| `AI_RISK_THRESHOLD` | `risk_threshold.value` in `metadata.json` | Optional override |
| `GENERATED_DIR` | `policies/generated` | Where validated Rego files are written (OPA loads it with `--watch`) |
| `APPEALS_DIR` | `appeals` | One JSON record per appeal, with its history |
| `OPA_PATH` | `opa` | opa binary used to validate generated files |
| `POLICY_DIR` | none | The application's policy folder; its `opa test` must still pass |
| `OBJECT_IDENTITY` | `false` | Allow "object is <id>" in candidates (objects that are systems, as in the Amazon data) |
| `APPEAL_CANDIDATES` | `8` | How many candidate patterns an appeal returns |
| `AUTO_APPLY_MAX_USERS`, `AUTO_APPLY_MAX_PAIRS`, `AUTO_APPLY_MAX_MEAN_RISK` | `5`, `50`, `0.5` | Above any of these a rule is "large" and needs `acknowledge_scope` |

Appeals need `graph.json` and `access.json` in the model folder; without them only `/risk` runs.

## `POST /risk`

```json
{"user": "user_0", "object": "resource_HOST_100"}
```

```json
{"risk": 0.0123, "high_risk": false, "threshold": 0.978, "reason": null}
```

- `high_risk` is true when `risk > threshold`. OPA only reads `high_risk`.
- If the user or object has no embedding, `risk` is `null`, `high_risk` is false and `reason`
  says which one is unknown. The policy decision stands.
- The service has no authentication; it must only be reachable by OPA (internal network).

## Appeals

```
POST /corax/appeals                {"user": "lecturer_budi", "object": "student_candra", "action": "read_grades", "reason": "..."}
  → 201 {"id": "appeal-0001", "status": "exception_applied", "neighbours": [...],
         "candidates": [{"index": 1, "pattern": "...", "users": 3, "pairs": 12, "support": 0.6, ...}, ...]}

POST /corax/appeals/appeal-0001/confirm   {"candidate": 3, "acknowledge_scope": false}
  → 200 {"status": "rule_applied", "chosen": {...scope, tier...}, "validation": [...]}
  → 409 when the rule is large and acknowledge_scope is false (the scope is in the response)
  → 422 when the rule fails validation (nothing is written)
POST /corax/appeals/appeal-0001/confirm   {"candidate": null}
  → 200 {"status": "exception_only"}
```

- The exception (`<id>-exception.rego`) is written as soon as the appeal is created; the rule
  (`<id>-rule.rego`) only after the admin picks a candidate. Both are validated with opa first and
  written atomically, so OPA never loads half a file.
- An appeal is confirmed once. The admin id comes from the `x-corax-user` header that OPA sets
  after verifying the JWT; ai-corax must therefore only be reachable through Envoy for `/corax/`,
  and `/risk` only from OPA.
