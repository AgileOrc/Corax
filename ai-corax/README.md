# ai-corax

FastAPI service called by OPA and by admins. It reads the folder written by `hgnn-job`
(`embeddings.npz`, `node_ids.json`, `metadata.json`) and does not need torch.

| Endpoint | Caller | Does | Status |
|---|---|---|---|
| `POST /risk` | OPA (`http.send`), only after the policy allowed a request | Returns `risk = 1 − σ(h_user · h_object)` from the HGNN embeddings | Built |
| `GET /health` | Checks, demo | Model info: target edge type, risk threshold, number of users and objects, whether appeals are on | Built |
| `POST /appeals` | Admin, through Envoy and OPA | Exact exception (validated, written at once) → similar cases → candidate patterns | Built |
| `POST /appeals/{id}/pick` | Admin | The admin picks a candidate: tier; small → validated rule written, large → waits | Built |
| `POST /appeals/{id}/confirm` | Admin | Confirms a large-scope rule (validated, then written) | Built |
| `POST /appeals/{id}/reject` | Admin | Stops an open appeal; only the exception stays | Built |
| `GET /appeals/{id}` | Admin | The appeal's state | Built |

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
| `GENERATED_DIR` | `policies/generated` | Where exceptions and rules are written; OPA loads it with `--watch --ignore=.*` |
| `STATE_DIR` | `state` | Appeal states (`appeals/<id>.json`) and `audit.jsonl`; OPA does not load it |
| `OPA_PATH` | `opa` | OPA binary that validates every exception and rule |
| `POLICY_DIR` | (none) | The application's policy folder, for `opa test` during validation |
| `AUTO_APPLY_MAX_USERS`, `AUTO_APPLY_MAX_PAIRS`, `AUTO_APPLY_MAX_MEAN_RISK` | `5`, `50`, `0.5` | Small tier limits (`tier.py`) |
| `APPEAL_OBJECT_VALUES`, `APPEAL_OBJECT_IDENTITY` | off | Allow `object has …` / `object is …` predicates (Amazon: identity) |

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

`appeals.py`, on top of `similar.py`, `patterns.py`, `tier.py`, `rules.py` and `validate.py`. The admin has
approved one appeal; the gateway checked that the caller is an admin (`policy/corax/admin.rego`).

```
POST /appeals {"appeal_id": "APL-0101", "user": "employee_E001", "object": "document_D016", "action": "read"}
  1. exception: render_exception → validate (syntax, whitelist, app tests, equivalence) → <id>-exception.rego
  2. similar cases (k = 10, at most 2 per user) → candidate patterns, narrowest first
  → {"status": "awaiting_choice", "candidates": [{"number": 1, "pattern": "...", "users": 4, "pairs": 45, ...}]}
     (no candidate: "exception_only")

POST /appeals/APL-0101/pick {"candidate": 1}
  3. opened pairs → tier (users, pairs, mean risk) → render_rule
     small: validate → <id>-rule.rego          → "applied" (or "rule_rejected" with the failed check)
     large: nothing written yet                → "awaiting_confirmation" with the reasons
POST /appeals/APL-0101/confirm                 → validate → <id>-rule.rego → "applied"
POST /appeals/APL-0101/reject                  → "rejected": no rule, the exception stays
```

Every response is the appeal's state (`STATE_DIR/appeals/<id>.json`): similar cases with their risk, the candidates,
the picked pattern with its tier and Rego, and the validation checks. Every step is a line in `STATE_DIR/audit.jsonl`
with the admin's name (the token's `sub`; the token was verified by OPA at the gateway). Appeals need `graph.json` and
`access.json` in the model folder (written by `hgnn-job/run.py`); without them `/appeals` answers 503.

The whole loop through Envoy and OPA, with a web page: [deploy/README.md](../deploy/README.md).
