# Architecture

Corax sits in front of an application and decides every request to it. It has an online part, which
handles requests and appeals, and an offline part, which trains the graph model the online part reads.

Three principles shape it (details in [Security](security.md)): policy code is the only source of allow
decisions, the AI can only turn an allow into a deny, and every rule from an appeal is validated, logged
and revoked by deleting its file.

## Components

![Corax components](../assets/architecture-components.png)

| Component | Does | Reads | Writes | Reachable from |
|---|---|---|---|---|
| Envoy | Proxy in front of the application, asks OPA about every request (`ext_authz`) | | | Clients |
| OPA | Policy engine: JWT, route, policy, AI risk call | `policy/`, the application's rules, `policies/generated/`, `data.json`, `graph.json` | | Envoy only |
| `service` | `/risk` for OPA, `/corax/appeals` for admins | Model folder, `data.json` | `policies/generated/`, appeal records | OPA and Envoy only |
| `hgnn` | Offline job: trains the model and exports it (`python -m hgnn`) | `nodes.csv`, `edges.csv` | Model folder | Nobody; runs as a job |

## Request path

<!-- TODO image: client → Envoy → OPA (1 JWT + route, 2 policy) → deny 403 | allow → service /risk (3) → 4 allow or 403 -->
![Request path](../assets/architecture-request.png)

1. **Identity and route:** OPA verifies the JWT (the user is its `sub`) and matches the method and path to a route, the object id comes only from the URL path, never from the query string or body.
2. **Policy:** The application's rules and the rules from appeals decide. A deny ends here with 403.
3. **Risk check:** Only after an allow, OPA asks the service for the risk of this (user, object) pair. Detailed explaination [here](risk-score.md).
4. **Decision:** The request goes through unless the risk is above the threshold.

The deny-only rule is written out in Rego, so it can be audited:

```rego
allow if {
	policy_allow
	not ai_high_risk
}
```

Listed admins reach the Corax admin routes without the risk check, and the exact pair an admin approved
in an appeal skips it too, [for more details](../reference/policy.md).

| Failure | Result |
|---|---|
| Missing, expired or forged token | 403, `missing or invalid token` |
| Method and path match no route | 403, `no matching route` |
| OPA unreachable | Envoy denies everything (`failure_mode_allow: false`) |
| Service down or slower than `ai.timeout` | The policy decision stands, `allowed without AI check` |
| User or object unknown to the model (added after the last training) | The policy decision stands, `allowed without AI check` |

## Appeal path

<!-- TODO image: admin → Envoy → OPA (admin?) → service; phase 1 create, phase 2 confirm (small / large → 409 → acknowledge or exception only), phase 3 revoke; files written to policies/generated/, OPA reloads -->
![Appeal path](../assets/architecture-appeal.png)

**Phase 1: the admin files the appeal**, `POST /corax/appeals`.

1. The exact exception for the appellant is written at once.
2. kNN finds the most similar pairs that have no access yet.
3. Candidate rules are built from the appellant's own facts and returned, narrowest first, with the users
   and pairs each one would open.

**Phase 2: the admin picks a candidate**, `POST /corax/appeals/{id}/confirm`.

4. The scope of the chosen rule is computed: share of users, new pairs, mean risk.
5. Tier: a small rule continues; a large one returns 409 until the admin confirms again with
   `acknowledge_scope`. The admin can also keep only the exception.
6. The rule is written as Rego from a fixed template and validated (syntax, whitelist, the application's
   tests, equivalence with the pattern). A rule that fails is not written.
7. The file is written atomically to `policies/generated/`; OPA, which watches the folder, loads it within
   milliseconds.

**Phase 3 (optional): revoke.** Deleting the rule's file removes it, OPA reloads the same way.

Policy files change only on disk. OPA's REST API is never used for writes and is not exposed. Details of
each step: [Appeals](appeals.md).

| Written | Where | When |
|---|---|---|
| `<id>-exception.rego` (package `app.exceptions`) | `policies/generated/` | Phase 1 |
| `<id>-rule.rego` (package `app.generated`) | `policies/generated/` | Phase 2, if the admin picks a rule |
| Appeal record with its history (audit log) | `appeals/` | Every step |

## Data and files

| File | Written by | Read by | Content |
|---|---|---|---|
| `embeddings.npz`, `node_ids.json` | `hgnn` | service | One vector per node |
| `metadata.json` | `hgnn` | service | Settings, metrics, risk threshold |
| `graph.json` | `hgnn` | service, OPA (`data.corax.graph`) | Facts of every node: department, role, … |
| `access.json` | `hgnn` | service | Access history, to skip pairs that already have access |
| `data.json` | Operator | OPA, service | JWT settings, routes, AI address, admin list ([Policy](../reference/policy.md)) |
| `policies/generated/*.rego` | service | OPA | Rules and exceptions from appeals |
| `appeals/*.json` | service | service, admins | Appeal records |

After retraining, the new model folder replaces the old one: the service reads it on restart, and OPA
needs the new `graph.json` in its data folder.

## Trust boundaries

- **Only Envoy is reachable from outside:** OPA, the service and the application sit on the internal
  network.
- **`/risk` has no authentication:** and must stay reachable by OPA only.
- **Appeals are checked twice:** OPA lets only `config.admin.users` reach `/corax/*`, and the service
  verifies the admin's JWT again with the same key and admin list, so reaching the service directly does not bypass the check.
- **No write API for policies:** Rules reach OPA only as files in a folder the service writes.

## Deployment

`deploy/docker-compose.yml` runs Envoy, OPA and the service in front of a stand-in API, the service and
OPA share the `policies/generated` volume, so OPA sees new files at once. </br> Read
[full stack](../getting-started/full-stack.md)
</br>What production still needs (identity provider keys,
TLS between components, health checks) is in the [roadmap](../roadmap.md).
