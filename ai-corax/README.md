# ai-corax

FastAPI service called by OPA and by admins. It reads the folder written by `hgnn-job`
(`embeddings.npz`, `node_ids.json`, `metadata.json`) and does not need torch.

| Endpoint | Caller | Does | Status |
|---|---|---|---|
| `POST /risk` | OPA (`http.send`), only after the policy allowed a request | Returns `risk = 1 − σ(h_user · h_object)` from the HGNN embeddings | Built |
| `GET /health` | Checks, demo | Model info: target edge type, risk threshold, number of users and objects | Built |
| `POST /appeals` | Admin, through Envoy and OPA | Exact exception → similar cases → pattern → tier → validated Rego file | Not built yet |
| `POST /appeals/{id}/confirm` | Admin | Confirms a large-scope rule | Not built yet |

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
