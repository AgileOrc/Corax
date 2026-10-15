# ai-corax

FastAPI service called by OPA and by admins. Not built yet.

| Endpoint | Caller | Does |
|---|---|---|
| `POST /risk` | OPA (`http.send`), only after the policy allowed a request | Returns `risk = 1 − σ(h_user · h_object)` from the HGNN embeddings |
| `POST /appeals` | Admin, through Envoy and OPA | Exact exception → similar cases → pattern → tier → LLM → validated Rego file |
| `POST /appeals/{id}/confirm` | Admin | Confirms a large-scope rule |

See [docs/ai-design.md](../docs/ai-design.md), sections 2, 4–7.
