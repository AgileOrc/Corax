# Getting started

Install Corax, create the dummy data and train the model once. That model lets you try Corax locally
without Docker. The end-to-end demo with Docker trains its own. Run every command from the repository
root.

## 1. Install

Python 3.11 or newer.

```bash
python -m venv .venv
```

Activate it: `.venv\Scripts\Activate.ps1` (PowerShell), `source .venv/Scripts/activate` (Git Bash) or
`source .venv/bin/activate` (Linux, macOS). Then:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r hgnn/requirements.txt -r service/requirements.txt -r requirements-dev.txt
```

Pick the CUDA build of torch instead of `cpu` if you have a GPU. The dummy data trains in seconds on CPU.

## 2. Create the dummy data and train once

```bash
python scripts/prepare/make_dummy.py output/dummy-data
python -m hgnn --data output/dummy-data --target-relation accessed --out output/dummy --learning-rate 0.01 --patience 50
```

The dummy data is a small graph of users, objects and how they are related. Its `accessed` edges are the
access the current policy allows. Training holds out 10% of those edges as a test set the model never
sees. The result is the model folder `output/dummy` ([Data and files](how-it-works.md#data-and-files)).

## 3. End-to-end demo with Docker

Real requests through Envoy, OPA and the service, in front of a document app with a web frontend. This shows
the deny-only AI check on live requests and OPA loading a rule from an appeal without a restart. The demo
trains its own model on synthetic company data, so it does not need step 2.

![End-to-end demo](assets/full-stack.png)

| Container | Role | Port |
|---|---|---|
| `envoy` | Gateway: asks OPA about every request, forwards the allowed ones | `8080` |
| `opa` | Policy engine: Corax's framework, the app's rules and the rules from appeals | internal |
| `service` | `/risk` for OPA, `/corax/*` for admins | internal |
| `app` | The document app (FastAPI and SQLite), with no access checks of its own | internal |
| `web` | The app's web frontend | internal, through Envoy |
| `console` | The Corax console, to send requests and handle appeals by hand | `8090` |

The service and OPA share a volume for the rules from appeals, and OPA watches it (`--watch`), so a new
rule is live without a restart. Both run inside Linux, so the file events reach OPA. A folder on Windows
bind-mounted into a container often does not deliver them.

### Run

Needs only Docker. From the repository root:

```bash
docker compose -f deploy/docker-compose.yml run --rm prepare
```

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

Then open http://localhost:8080 (the document app) and http://localhost:8090 (the console). To see every
case as a log:

```bash
docker compose -f deploy/docker-compose.yml run --rm demo
```

To start again from no appeals, remove the volumes:

```bash
docker compose -f deploy/docker-compose.yml down -v
```

The full walkthrough, as employees and as the admin: [Running the demo](demo.md). The app, its rules and
its frontend are in [`demo/`](../demo/README.md).

## 4. Without Docker

### The AI predicts access it has never seen

```bash
python scripts/demo_risk.py --model-dir output/dummy
```

The script scores pairs from the test split and puts the true answer next to the AI's:

| Row | Meaning | The AI should |
|---|---|---|
| **allowed** | A real access the model never saw | Let it pass |
| **not allowed** | A random pair without access | Deny it |
| **peer has it** | A pair without access, but a peer of the user has the object. It looks normal, the hardest case | Deny it |

```
threshold 0.992; all held-out pairs, none seen during training:
  allowed      49/49 let through (100%)
  not allowed  85/98 denied (87%)
  peer has it  32/47 denied (68%)
```

A pair is denied when its risk is above the threshold, the same rule `/risk` uses. In the real flow the AI
only sees requests the policy already allowed. The "not allowed" rows show what it would catch if a
wrong or over-broad rule let such a request through. A miss there means the AI adds no deny and the
policy decision stands.

### Appeals, end to end with OPA

Needs the [OPA binary](https://www.openpolicyagent.org/docs/latest/#running-opa).

```bash
python scripts/demo_appeal.py --model-dir output/dummy --opa path/to/opa
```

The script runs the same code as the `/corax/appeals` endpoints (without HTTP and JWT), writes the Rego
files to a temporary folder (`--out` keeps them), then lets OPA decide on them.

In every appeal the admin accepts the request, and Corax proposes candidate rules. The admin accepts one
of them, by what it says and not by its size, or none. Corax then computes the tier of the accepted rule
from its share of users, new pairs and mean risk. The script plays the admin:

| Appeal | Rule the admin accepts | Tier (computed by Corax) | Result |
|---|---|---|---|
| 1 | Users with the appellant's role may access objects of their own group | **Small** | Written at once. Another user in the same situation, who never appealed, is allowed |
| 2 | Everyone in a group may access objects of that group | **Large** | 409 response code, nothing written until the admin confirms again with `acknowledge_scope` |
| 3 | None, the appeal is a one-off | | **Exception only**: just that one pair is opened |

To look at a single appeal with all its similar cases and candidates, without writing anything:

```bash
python scripts/similar_cases.py --model-dir output/dummy --user <user> --object <object> --pick 1
```

How appeals work: [Appeal](how-it-works.md#appeal-path).

### The risk endpoint as OPA calls it

```bash
CORAX_MODEL_DIR=output/dummy uvicorn main:app --app-dir service --port 8000
```

```bash
curl -X POST localhost:8000/risk -H "Content-Type: application/json" -d '{"user": "<user>", "object": "<object>"}'
```

```json
{"risk": 0.99993, "high_risk": true, "threshold": 0.992, "reason": null}
```

User and object ids are listed in `output/dummy/node_ids.json`. `/risk` uses the embeddings of the whole
graph, so its numbers differ slightly from `demo_risk.py`, which recomputes them without the test edges.

## Larger datasets

The same flow (prepare, `python -m hgnn`, evaluate) runs on the Amazon Access Samples dataset and the
Xu & Stoller ABAC policies. Read [scripts](reference.md#scripts) and [evaluation](evaluation.md).
