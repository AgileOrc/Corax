# service

The Corax service. OPA calls it for the risk of a request, and admins call it to handle appeals. It
reads the model folder written by `python -m hgnn` and needs only numpy, not torch.

## Files

| File | Does |
|---|---|
| `main.py` | The API: `POST /risk`, `GET /health` and the `/corax/appeals` endpoints |
| `risk.py` | Risk score from the model's vectors |
| `similar.py` | Finds the most similar cases for an appeal (kNN) |
| `patterns.py` | Builds the candidate rules from the appellant's facts |
| `tier.py` | Decides whether a rule is small or large |
| `rules.py` | Writes a rule or an exception as Rego |
| `validate.py` | Checks a Rego file with opa before it is written |
| `appeals.py` | The appeal flow and its records |
| `auth.py` | Verifies the admin's JWT |
| `graph.py` | Reads the graph and the access history from the model folder |
| `config.py` | Settings from environment variables |

## Run

```bash
pip install -r service/requirements.txt
CORAX_MODEL_DIR=<model folder> uvicorn main:app --app-dir service --port 8000
```

Endpoints, environment variables and admin authentication: [docs/reference.md](../docs/reference.md#service-api).
