# Corax

Corax is policy-as-code authorization for REST APIs against Broken Object Level Authorization (BOLA,
OWASP API1). Deterministic Rego policies make every allow decision.
</br></br>A graph neural network adds 2
things on top:
* A per-request risk check that can only deny
* An appeal flow that turns an admin's
decision into a new, validated rule.

## Why

Authorization checks written ad hoc in each service are inconsistent, undocumented and hard to audit,
which is why BOLA keeps happening. Pure machine-learning access control is not the answer either, models are hard to update when rules change and can be fooled by manipulated attributes.

Corax keeps **policy code as the source of truth** and uses AI only where it helps:

| Layer | Role | Can it grant access? |
|---|---|---|
| Policy code (OPA / Rego) | Final authority, deterministic | Yes |
| AI risk check (every request) | Flags requests that passed policy but do not fit the access graph | **No** |
| Appeal (admin flow) | Finds similar cases when an admin approves an exception and proposes a rule | Only through a validated rule. Large rules need admin confirmation |

## Components

| Folder | Does |
|---|---|
| `policy/` | Generic Rego framework: JWT, route matching, AI risk call, deny-only rule |
| `service/` | FastAPI: `/risk` for OPA, `/corax/appeals` for admins. Needs only numpy, no torch |
| `hgnn/` | Trains the heterogeneous GraphSAGE model and exports one embedding per node (`python -m hgnn`) |
| `scripts/` | Dataset preparation, evaluation, and the demo scripts |

## Where to go next

* [Getting started](getting-started.md): install, train the model once, run the demo with or without Docker.
* [How Corax works](how-it-works.md): components, the request path, the risk score and the appeal path.
* [Security](security.md): invariants, threats and mitigations, scope, limitations and future work.
* [Evaluation](evaluation.md): results on Amazon Access Samples and the Xu & Stoller ABAC policies, and the references.
* [Reference](reference.md): service API, policy, HGNN training, scripts and data format.

## Prior research

Corax's risk model implements the heterogeneous graph method of [[1]](evaluation.md#references). Machine-learning
access control and its administration [[2]](evaluation.md#references), [[3]](evaluation.md#references), knowledge-graph access
decisions [[4]](evaluation.md#references) and attacks on heterogeneous graph models [[5]](evaluation.md#references) shaped the
design. The ABAC policies of [[6]](evaluation.md#references) are the appeal benchmark. </br>[Full references list](evaluation.md#references)
