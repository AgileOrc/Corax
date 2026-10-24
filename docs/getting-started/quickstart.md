# Quick start

Install Corax, create the dummy data and train the model once. The trained model is what the
[full stack](full-stack.md) demo runs on, the same model also lets you try Corax locally, without Docker.
Run every command from the repository root.

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

Pick the CUDA build of torch instead of `cpu` if you have a GPU; the dummy data trains in seconds on CPU.

## 2. Create the dummy data and train once

```bash
python scripts/prepare/make_dummy.py output/dummy-data
python -m hgnn --data output/dummy-data --target-relation accessed --out output/dummy --learning-rate 0.01 --patience 50
```

The dummy data is a small graph of users, objects and how they are related; its `accessed` edges are the
access the current policy allows. Training holds out 10% of those edges as a test set the model never
sees. The result is the model folder `output/dummy` ([Data and files](../concepts/architecture.md#data-and-files)).

## 3. Run the demo

With Docker, continue with the [full stack](full-stack.md): real requests through Envoy, OPA and the
service. Without Docker, the scripts below show the same AI on the trained model.

## Without Docker

### The AI predicts access it has never seen

```bash
python scripts/demo_risk.py --model-dir output/dummy
```

The script scores pairs from the test split and puts the true answer next to the AI's:

| Row | Meaning | The AI should |
|---|---|---|
| **allowed** | A real access the model never saw | Pass |
| **not allowed** | A random pair without access | Deny |
| **peer has it** | A pair without access, but a peer of the user has the object; it looks normal, the hardest case | Deny |

```
threshold 0.992; all held-out pairs, none seen during training:
  allowed      49/49 let through (100%)
  not allowed  85/98 denied (87%)
  peer has it  32/47 denied (68%)
```

A pair is denied when its risk is above the threshold, the same rule `/risk` uses. In the real flow the AI
only sees requests the policy already allowed: the "not allowed" rows show what it would catch if a wrong
or over-broad rule let such a request through. A miss there means the AI adds no deny; the policy
decision stands.

### Appeals, end to end with OPA

Needs the [OPA binary](https://www.openpolicyagent.org/docs/latest/#running-opa).

```bash
python scripts/demo_appeal.py --model-dir output/dummy --opa path/to/opa
```

The script runs the same code as the `/corax/appeals` endpoints (without HTTP and JWT), writes the Rego
files to a temporary folder (`--out` keeps them), then lets OPA decide on them:

| Appeal | The admin picks | Result |
|---|---|---|
| 1 | A narrow rule | **Small**: written at once; another user in the same situation, who never appealed, is allowed |
| 2 | A broad rule | **Large**: 409, nothing written until the admin acknowledges the scope |
| 3 | No rule: the appeal is a one-off and every candidate is large | **Exception only**: just that one pair is opened |

To look at a single appeal with all its similar cases and candidates, without writing anything:

```bash
python scripts/similar_cases.py --model-dir output/dummy --user <user> --object <object> --pick 1
```

How appeals work: [Appeals](../concepts/appeals.md).

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

The same flow (prepare --> `python -m hgnn` --> evaluate) runs on the Amazon Access Samples dataset and the
Xu & Stoller ABAC policies. 
</br>Read [scripts](../reference/scripts.md) and [evaluation](../evaluation.md).
