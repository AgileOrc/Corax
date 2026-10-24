# Service API

FastAPI service called by OPA and by admins. It reads the folder written by `hgnn`
(`embeddings.npz`, `node_ids.json`, `metadata.json`) and does not need torch.

| Endpoint | Caller | Does | Status |
|---|---|---|---|
| `POST /risk` | OPA (`http.send`), only after the policy allowed a request | Returns `risk = 1 − σ(h_user · h_object)` from the HGNN embeddings | Built |
| `GET /health` | Checks, demo | Model info: target edge type, risk threshold, number of users and objects | Built |
| `POST /corax/appeals` | Admin, through Envoy and OPA | Writes the exact exception at once, returns similar cases and candidate patterns | Built |
| `GET /corax/appeals/{id}` | Admin | The appeal record and its history (audit log) | Built |
| `POST /corax/appeals/{id}/confirm` | Admin | Writes the chosen candidate as a validated rule, or keeps only the exception | Built |

Concepts: [Risk score](../concepts/risk-score.md), [Appeals](../concepts/appeals.md).

## Run

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
| `CORAX_CONFIG` | none | The application's `data.json` (the one OPA loads). Its `corax.config.jwt` and `corax.config.admin.users` are used to verify admins; without it the appeal endpoints return 503 |
| `OPA_PATH` | `opa` | opa binary used to validate generated files |
| `POLICY_DIR` | none | The application's policy folder; its `opa test` must still pass |
| `OBJECT_IDENTITY` | `false` | Allow "object is <id>" in candidates (objects that are systems, as in the Amazon data) |
| `APPEAL_CANDIDATES` | `8` | How many candidate patterns an appeal returns |
| `AUTO_APPLY_MAX_USER_SHARE` | `0.4` | Share of all users (0–1, e.g. `0.5` = 50%) that may get new access; above it a rule is "large" |
| `AUTO_APPLY_MAX_PAIRS`, `AUTO_APPLY_MAX_MEAN_RISK` | `50`, `0.5` | New (user, object) pairs and their mean risk; above either a rule is "large" |

A "large" rule needs `acknowledge_scope`. No regulation fixes these numbers (ISO 27001, NIST 800-53 and PCI DSS ask that access grants are approved and logged, not for a size limit); set them to the organization's risk appetite. `AUTO_APPLY_MAX_USER_SHARE=0` makes every rule wait for an admin.

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

- The exception (`<id>-exception.rego`) is written as soon as the appeal is created; the rule
  (`<id>-rule.rego`) only after the admin picks a candidate. Both are validated with opa first and
  written atomically, so OPA never loads half a file.
- An appeal is confirmed once.
- Candidates skip values that are too specific to the appealed pair: a value both the user and the
  object have (the `user.X = object.Y` candidate covers it for every value), and a value of an
  attribute with several values (e.g. one of the projects a user works on). Otherwise one slice per
  value would rank above the general rule, because it opens fewer pairs.

## Admin authentication

Every appeal endpoint needs `Authorization: Bearer <JWT>` of an admin. corax-service checks it itself,
even though OPA already did, so calling corax-service directly does not bypass the check:

| Check | Result |
|---|---|
| No token, not `Bearer`, bad signature, expired, wrong `iss` / `aud`, no `exp` or `sub` | 401 |
| Valid token, `sub` not in `corax.config.admin.users` | 403 |
| `CORAX_CONFIG` not set or has no `corax.config.jwt` | 503 (fails closed) |

- Key, issuer, audience and admin list come from the same `data.json` as OPA, re-read when the
  file changes, so both always agree.
- `secret` allows only HS256; `cert` (a PEM public key) allows only RS256 / ES256. With a public
  key corax-service can verify tokens but never create them.
- The `x-corax-user` header is ignored; the audit log records the `sub` of the verified token.
- `/risk` has no authentication and must stay on the internal network, reachable only by OPA.
