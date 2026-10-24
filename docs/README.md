# Corax

Corax is policy-as-code authorization for REST APIs against Broken Object Level Authorization (BOLA,
OWASP API1). Deterministic Rego policies make every allow decision. A graph neural network adds two
things on top: a per-request risk check that can only deny, and an appeal flow that turns an admin's
decision into a new, validated rule.

## Why

Authorization checks written ad hoc in each service are inconsistent, undocumented and hard to audit,
which is why BOLA keeps happening. Pure machine-learning access control is not the answer either:
models are hard to update when rules change and can be fooled by manipulated attributes.

Corax keeps **policy code as the source of truth** and uses AI only where it helps:

| Layer | Role | Can it grant access? |
|---|---|---|
| Policy code (OPA / Rego) | Final authority, deterministic | Yes |
| AI risk check (every request) | Flags requests that passed policy but do not fit the access graph | **No, it can only deny** |
| Appeal (admin flow) | Finds similar cases when an admin approves an exception and proposes a rule | Only through a validated rule; large rules need admin confirmation |

## Components

| Folder | Does |
|---|---|
| `policy/` | Generic Rego framework: JWT, route matching, AI risk call, deny-only rule |
| `service/` | FastAPI: `/risk` for OPA, `/corax/appeals` for admins. Needs only numpy, no torch |
| `hgnn/` | Trains the heterogeneous GraphSAGE model and exports one embedding per node (`python -m hgnn`) |
| `scripts/` | Dataset preparation, evaluation, and the demo scripts |

## Where to go next

* [Quick start](getting-started/quickstart.md): see the model predict, without Envoy, OPA or Docker.
* [Full stack](getting-started/full-stack.md): the demo on real requests through Envoy and OPA, with Docker.
* [Architecture](concepts/architecture.md): the request path and the appeal path.
* [Evaluation](evaluation.md): results on Amazon Access Samples and the Xu & Stoller ABAC policies.

## Prior research

Corax's risk model implements the heterogeneous graph method of [[1]](references.md). Machine-learning
access control and its administration [[2]](references.md), [[3]](references.md), knowledge-graph access
decisions [[4]](references.md) and attacks on heterogeneous graph models [[5]](references.md) shaped the
design; the ABAC policies of [[6]](references.md) are the appeal benchmark. Full list:
[References](references.md).
