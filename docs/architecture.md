# Architecture

Corax is deployed in front of an application and authorizes every request made to it. The system has an online
part, which evaluates requests and processes appeals, and an offline part, which trains the graph model that the
online part reads.

The design rests on three principles, detailed under [Security](#security). Policy code is the only source of allow
decisions. The AI can only turn an allow into a deny. Every rule produced by an appeal is validated before it takes
effect, recorded together with the access it grants and every later use of that access, and revoked by deleting its
file.

## Components

![Corax components](assets/architecture-components.png)

| Component | Responsibility | Reads | Writes | Reachable from |
|---|---|---|---|---|
| Envoy | Proxy in front of the application. Consults OPA on every request (`ext_authz`) | | | Clients |
| OPA | Policy engine. Verifies the JWT, matches the route, evaluates the policy and calls the risk service | `policy/`, the application's rules, `policies/generated/`, `data.json`, `graph.json` | | Envoy, and internal services that query it directly |
| `service` | Serves `/risk` and `/usage` to OPA, and `/corax/*` to administrators and users | Model folder, `data.json` | `policies/generated/`, appeal records, access snapshots, usage logs | OPA and Envoy only |
| `hgnn` | Offline job that trains and exports the model (`python -m hgnn`) | `nodes.csv`, `edges.csv` | Model folder | Not exposed |

### Deployment modes

Corax separates the authorization decision from its enforcement. OPA, loaded with the Corax policy framework and
backed by the risk service, acts as the policy decision point (PDP). The policy enforcement point (PEP) can be
deployed in two ways.

**Gateway enforcement (sidecar).** Envoy is deployed in front of the protected API and consults OPA through its
`ext_authz` filter for every inbound request. Requests are authorized before they reach the application, which
therefore carries no authorization logic of its own. In the demo, every call to the document application takes this
path.

**Application enforcement (direct PDP queries).** A gateway or service queries the OPA REST API and enforces the
decision itself. `POST /v1/data/corax/authz/allowed_objects`, for example, reduces a collection to the objects a
subject is permitted to access. The demo's document application uses this query to scope its catalog.

Both modes evaluate the same policy, including the rules generated from appeals. The `allowed_objects` query
evaluates the policy only and does not invoke the risk service, because it filters a collection rather than
authorizing access to a single object. The risk check is applied when the subject subsequently retrieves an object
through Envoy. A service that queries OPA directly is responsible for enforcing the decision, and OPA must be
reachable only from the internal network.

## Request path

![Request path](assets/architecture-request.png)

1. **Identity and route.** OPA verifies the JWT, whose `sub` identifies the user, and matches the method and path to
   a configured route. The object identifier is taken only from the URL path, never from the query string or body.
2. **Policy.** The application's rules and the rules generated from appeals are evaluated. A deny ends the request
   with 403.
3. **Risk check.** Only after an allow, OPA requests the risk of the (user, object) pair from the service. See
   [Risk score](ai-model-and-evaluation.md#risk-score).
4. **Decision.** The request proceeds unless the risk exceeds the threshold.

The deny-only rule is written in Rego, which keeps it open to audit:

```rego
allow if {
	policy_allow
	not ai_high_risk
}
```

Administrators listed in the configuration reach the Corax administrative routes without a risk check. The exact
(user, object) pair an administrator approves in an appeal also bypasses it. See [Policy](#policy).

| Failure | Behavior |
|---|---|
| Missing, expired or forged token | 403, `missing or invalid token` |
| No route matches the method and path | 403, `no matching route` |
| OPA unreachable | Envoy denies every request (`failure_mode_allow: false`) |
| Risk service unavailable or slower than `ai.timeout` | The policy decision stands, `allowed without AI check` |
| User or object unknown to the model (added after the last training) | The policy decision stands, `allowed without AI check` |

## Data and files

| File | Written by | Read by | Content |
|---|---|---|---|
| `embeddings.npz`, `node_ids.json` | `hgnn` | service | One embedding vector per node |
| `metadata.json` | `hgnn` | service | Training settings, metrics and the risk threshold |
| `graph.json` | `hgnn` | service, OPA (`data.corax.graph`) | Attributes and relations of every node, such as department and role |
| `access.json` | `hgnn` | service | Access history, used to exclude pairs that already have access |
| `data.json` | Operator | OPA, service | JWT settings, routes, the risk service address and the administrator list ([Policy](#policy)) |
| `policies/generated/*.rego` | service | OPA | Rules and exceptions produced by appeals |
| `appeals/*.json` | service | service, administrators | Appeal records and access snapshots |
| `appeals/*-usage.jsonl` | service | service, administrators | Every use of access granted by an appeal |

After retraining, the new model folder replaces the previous one. The service loads it on restart, and OPA requires
the new `graph.json` in its data folder.

## Trust boundaries

- **Only Envoy is exposed externally:** OPA, the service and the application remain on the internal network.
- **`/risk` and `/usage` are unauthenticated:** They must be reachable by OPA only. `/usage` can only append to a
  usage log and cannot grant access.
- **Users see only their own access:** `GET /corax/me/access` derives the user from the verified token, never from
  the path, query string or headers.
- **Appeals are authorized twice:** OPA admits only `config.admin.users` to `/corax/*`, and the service verifies the
  administrator's JWT again with the same key and administrator list. Reaching the service directly therefore does
  not bypass the check.
- **Policies have no write API:** Rules reach OPA only as files in a folder written by the service.

## Service API

A FastAPI service called by OPA and by administrators. It reads the model folder written by `hgnn`
(`embeddings.npz`, `node_ids.json`, `metadata.json`) and does not depend on PyTorch.

| Endpoint | Caller | Function |
|---|---|---|
| `POST /risk` | OPA (`http.send`), only after the policy allows a request | Returns `risk = 1 − σ(h_user · h_object)` from the HGNN embeddings, and records the use when the access originates from an appeal |
| `POST /usage` | OPA, when an appeal exception allows a request | Records the use of an exception, since exceptions bypass `/risk` |
| `GET /health` | Health checks, demo | Model information: target edge type, risk threshold, number of users and objects |
| `POST /corax/appeals` | Administrator, through Envoy and OPA | Writes the exact exception immediately and returns the similar cases and candidate rules, each with its scope and tier. Returns 409 when the user already has the access. With `dry_run`, writes nothing and returns what the appeal would produce |
| `GET /corax/appeals/{id}` | Administrator | The appeal record and its history |
| `GET /corax/appeals/{id}/candidates/{n}` | Administrator | Preview of who would gain access to which objects if candidate `n` were accepted. Writes nothing |
| `POST /corax/appeals/{id}/confirm` | Administrator | Writes the accepted candidate as a validated rule, or keeps only the exception |
| `POST /corax/appeals/{id}/revoke` | Administrator | Deletes the rule, and optionally the exception, and records who revoked it |
| `GET /corax/rules` | Administrator | Every rule and exception from an appeal still in effect, with the access it granted and its usage, as data and as plain-language summaries |
| `GET /corax/me/access` | Any user with a valid token | The resources the user can reach through appeals. The user is taken only from the token |
| `GET /corax/suggestions?user=&limit=` | Administrator | Access the model expects but nobody has granted, for review. Writes nothing |
| `POST /corax/rank` | Administrator | The objects linked to a node, such as a department, that a user cannot reach yet, ranked for that user |

The underlying concepts are described in [Risk score](ai-model-and-evaluation.md#risk-score) and
[Appeal path](ai-model-and-evaluation.md#appeal-path).

### Run

```
pip install -r service/requirements.txt
CORAX_MODEL_DIR=output/gateway/hgnn uvicorn main:app --app-dir service --port 8000
```

| Variable | Default | Meaning |
|---|---|---|
| `CORAX_MODEL_DIR` | `output/hgnn` | Folder written by `hgnn` |
| `AI_RISK_THRESHOLD` | `risk_threshold.value` in `metadata.json` | Optional override of the threshold |
| `GENERATED_DIR` | `policies/generated` | Destination of validated Rego files, which OPA watches (`--watch`) |
| `APPEALS_DIR` | `appeals` | One JSON record per appeal, including its history |
| `CORAX_CONFIG` | none | The application's `data.json`, the same file OPA loads. Its `corax.config.jwt` and `corax.config.admin.users` are used to verify administrators. Without it, the appeal endpoints return 503 |
| `OPA_PATH` | `opa` | OPA binary used to validate generated files |
| `POLICY_DIR` | none | The application's policy folder, whose `opa test` must continue to pass |
| `OBJECT_IDENTITY` | `false` | Allows "object is <id>" in candidates, for objects that are systems, as in the Amazon data |
| `APPEAL_CANDIDATES` | `8` | Number of candidate patterns an appeal returns |
| `APPEAL_SIMILAR_MIN`, `APPEAL_SIMILAR_MAX`, `APPEAL_SIMILAR_MARGIN` | `5`, `30`, `0.03` | Selection of similar cases. Every case within the margin of the closest one is included, bounded by the minimum and maximum, so an appeal among many near identical cases draws on more of them |
| `APPEAL_RESOURCE_TYPE` | the object type of the model's target edge | The `resource_type` that generated rules and exceptions apply to. Set it when the routes name the type differently from the graph |
| `AUTO_APPLY_MAX_USER_SHARE` | `0.4` | Share of all users (0 to 1, so `0.5` is 50%) that may receive new access. A rule above it is large |
| `AUTO_APPLY_MAX_PAIRS`, `AUTO_APPLY_MAX_MEAN_RISK` | `50`, `0.5` | New (user, object) pairs and their mean risk. A rule above either is large |

A large rule requires `acknowledge_scope`. No regulation prescribes these values. ISO 27001, NIST 800-53 and PCI DSS
require that access grants are approved and logged, not that they stay below a size limit. Set them according to
the organization's risk appetite. `AUTO_APPLY_MAX_USER_SHARE=0` makes every rule wait for an administrator.

To change a limit, set it in the service's environment. With Docker, add it in `deploy/docker-compose.yml` under
`service` → `environment`:

```yaml
      AUTO_APPLY_MAX_USER_SHARE: "0.5"
      AUTO_APPLY_MAX_PAIRS: "100"
      AUTO_APPLY_MAX_MEAN_RISK: "0.5"
```

Then recreate the service with `docker compose -f deploy/docker-compose.yml up -d service`. Without Docker:

```bash
AUTO_APPLY_MAX_USER_SHARE=0.5 CORAX_MODEL_DIR=output/gateway/hgnn uvicorn main:app --app-dir service --port 8000
```

The document application demo sets `AUTO_APPLY_MAX_USER_SHARE` to `0.06` in `deploy/docker-compose.yml`, which
corresponds to 5 of its model's 86 employees. [Running the Demo](demo.md) assumes that limit. Under other limits, an
appeal may fall into a different tier.

Appeals require `graph.json` and `access.json` in the model folder. Without them, only `/risk` is available.

### `POST /risk`

```json
{"user": "employee_E049", "object": "document_D057", "action": "read"}
```

```json
{"risk": 0.0123, "high_risk": false, "threshold": 0.978, "reason": null}
```

- `high_risk` is true when `risk > threshold`. OPA reads only `high_risk`.
- When the user or object has no embedding, `risk` is `null`, `high_risk` is false, and `reason` identifies the
  unknown entity. The policy decision stands.
- `action` is optional. OPA sends it so that a use of appeal access is attributed to the correct rule.
- When a rule from an appeal opened the pair and the risk is not high, the request proceeds, and the service
  appends the use to `appeals/<id>-usage.jsonl`.
- The endpoint is unauthenticated and must be reachable by OPA only, on the internal network.

### `POST /usage`

Accepts the same body as `/risk`. OPA calls it only when an appeal exception allows a request, because exceptions
bypass `/risk`. It writes to the usage log only and never affects a decision. Like `/risk`, it is unauthenticated
and must remain on the internal network.

### Appeals

```
POST /corax/appeals                {"user": "employee_E049", "object": "document_D057", "action": "read", "reason": "..."}
  → 201 {"id": "appeal-0001", "status": "exception_applied", "neighbours": [...],
         "exception": {"description": "employee_E049 may read document_D057, an exception for this one document only."},
         "candidates": [{"index": 1, "description": "An employee may ...", "pattern": "...", "users": 3, "pairs": 12, ...}, ...]}

GET  /corax/appeals/appeal-0001/candidates/1
  → 200 {"description": "...", "scope": {...}, "affected": {"users": 4, "objects": 10, "by_user": [{"user": "employee_E085", "objects": ["document_D070", "document_D072"]}, ...]}}

POST /corax/appeals/appeal-0001/confirm   {"candidate": 1, "acknowledge_scope": false}
  → 200 {"status": "rule_applied", "chosen": {"description": "...", "scope": {...}}, "validation": [...]}
  → 409 when the rule is large and acknowledge_scope is false: the description, the scope and the first
        20 users who would gain access are in the response
  → 422 when the rule fails validation (nothing is written)
POST /corax/appeals/appeal-0001/confirm   {"candidate": null}
  → 200 {"status": "exception_only"}

POST /corax/appeals/appeal-0001/revoke    {"exception": false}
  → 200 {"status": "rule_revoked", ...}   (exception: true also removes the appellant's exception)
  → 409 when nothing is active to revoke
```

- `description` is a plain-language sentence derived from the same predicates as the Rego file, intended for the
  administrator. OPA enforces the Rego file. `pattern` expresses the same rule in technical form.
- The exception (`<id>-exception.rego`) is written when the appeal is created, and the rule (`<id>-rule.rego`) only
  after the administrator accepts a candidate. Both are validated with OPA first and written atomically, so OPA
  never loads a partial file.
- An appeal can be confirmed once.
- When access is granted, the exception immediately and the rule on acceptance, the service writes a snapshot of who
  gained access to which objects in `appeals/<id>-granted.json`. Every later use of that access is appended to
  `appeals/<id>-usage.jsonl`.
- Revoking through the endpoint deletes the file and records who revoked it and when. Deleting the file manually
  also removes the rule, but leaves no record, and `GET /corax/rules` flags the entry.
- Candidates exclude values too specific to the appealed pair. These include a value the user and the object share,
  which the `user.X = object.Y` candidate already covers for every value, and a single value of a multi-valued
  attribute, such as one of the projects a user works on. Otherwise a slice per value would rank above the general
  rule, because it opens fewer pairs.

### What the administrator and the user see

`GET /corax/rules` returns one entry per rule or exception still in effect, with a plain-language `summary`:

```
An employee may read a document when the employee and the document have the same department and the employee is a coordinator.
Approved as a rule by admin_01 on 29 Oct 2026 10:00 UTC.
4 people gained access to 10 documents.
Used 1 time by 1 person:
  29 Oct 2026 10:05 UTC  employee_E085 read document_D070
```

`GET /corax/me/access` returns only the resources, for the user identified by the token:

```json
{"user": "employee_E085", "resources": ["document_D070", "document_D072"]}
```

The list covers access from appeals only. Access granted by the application's own rules is not included.

### Suggested access and ranking a unit

The model is trained to predict access. Beyond denying pairs that do not fit, its predictions identify access a user
is likely to need but has not been granted. Both endpoints score a pair the same way, by the model's risk and by how
many of the user's 10 most similar users can already reach the object, through the access history or through
appeals. Neither endpoint writes anything. An administrator grants access through the appeal flow.

```
GET  /corax/suggestions?limit=20
  → 200 [{"user": "employee_E041", "object": "document_D101", "risk": 0.08, "peers": {"with_access": 10, "of": 10},
          "description": "10 of the 10 people most like employee_E041 can open document_D101."}, ...]

POST /corax/rank   {"user": "employee_E085", "relation": "owned_by", "node": "department_engineering"}
  → 200 {"objects": [...ranked as above, every document of the unit employee_E085 cannot reach yet...],
         "warning": null | "None of the people most like this user can open anything here. ..."}
```

- A pair is suggested when its risk is at most the threshold and at least half of the 10 peers can reach the object.
  Both values are design choices, not measured values (`service/suggest.py`).
- `rank` lists every object of the unit, best first, and issues a warning when no peer can reach any of them, since
  the unit may be the wrong one.
- `suggestions` evaluates every user against every object. Above 2,000,000 pairs it returns 422, and the request
  must be limited to one user (`?user=`).
- Both endpoints are restricted to administrators, because their results name objects the user cannot open.

### Administrator authentication

Every appeal endpoint requires an administrator's `Authorization: Bearer <JWT>`. The service verifies it
independently of OPA, so calling the service directly does not bypass the check.

| Condition | Result |
|---|---|
| No token, not `Bearer`, invalid signature, expired, wrong `iss` or `aud`, missing `exp` or `sub` | 401 |
| Valid token whose `sub` is not in `corax.config.admin.users` | 403, except for `GET /corax/me/access` |
| `CORAX_CONFIG` unset or without `corax.config.jwt` | 503 (fails closed) |

- The key, issuer, audience and administrator list come from the same `data.json` as OPA and are reloaded when the
  file changes, so both components always agree.
- `secret` permits HS256 only, and `cert` (a PEM public key) permits RS256 or ES256 only. With a public key the
  service can verify tokens but never issue them.
- The `x-corax-user` header is ignored. The audit log records the `sub` of the verified token.
- `/risk` is unauthenticated and must remain on the internal network, reachable by OPA only.

## Policy

A generic Rego framework shared by every application protected by Corax (package `corax.authz`).

```
Envoy ext_authz input
  1. verify the JWT                      → user.id = sub
  2. match method + path to a route      → action, resource {type, id, ...}
  3. admin_allow     = corax.* action AND user in config.admin.users   (Corax admin routes)
     self_allow      = corax.me.access AND a valid token                (a user's own access list)
     exception_allow = data.app.exceptions.allow  (the exact pair an admin approved in an appeal)
     policy_allow    = data.app.authz.allow       (the application's rules)
                    OR data.app.generated.allow   (rules added through appeals)
  4. ai_high_risk = POST corax-service /risk            (only when policy_allow and not an exception)
     POST corax-service /usage                         (only when exception_allow, for the usage log)
  5. allow = admin_allow OR self_allow OR exception_allow OR (policy_allow AND NOT ai_high_risk)
```

| File | Content |
|---|---|
| `request.rego` | JWT verification, route matching and the normalized `request` |
| `authz.rego` | `allow`, the risk check, `reason`, and `result` for opa-envoy-plugin |
| `authz_test.rego` | Tests, with the risk service and the application's rules mocked |
| `config.example.json` | Example configuration |

### What an application provides

**1. Rules** in package `app.authz` that define `allow`. Their `input` is the normalized request, never the raw
Envoy input:

```json
{
  "user": {"id": "employee_E049"},
  "action": "read",
  "resource": {"type": "document", "id": "document_D057"}
}
```

Appeals write two kinds of file to `policies/generated/`, each defining `allow`:

| Package | Content | Risk check |
|---|---|---|
| `app.exceptions` | Only the exact (user, action, object) the administrator approved | Bypassed, since the administrator reviewed it |
| `app.generated` | The broader rule derived from similar cases | Applied |

**2. Configuration** under `data.corax.config`, as in `config.example.json`:

| Key | Meaning |
|---|---|
| `jwt` | Constraints for `io.jwt.decode_verify`. Either `secret` (HS256, demo) or `cert` (JWKS or PEM, production), together with `iss` and `aud`. `exp` and `nbf` are always checked |
| `routes` | `method`, `path` with `:name` parameters, `action` and `resource_type`. Exactly one route must match, otherwise the request is denied. The `:id` parameter identifies the object sent to the risk service |
| `ai.url`, `ai.timeout` | Address of the risk service and the `http.send` timeout (default `20ms`). Without `ai`, no risk check is performed |
| `admin.users` | User identifiers (JWT `sub`) permitted to use the Corax administrative routes. Without it, no user is an administrator |
| `labels` | Optional readable names for plain-language sentences, in `actions`, `types`, `relations` and `nodes`, each mapping an identifier to text, for example `{"types": {"document": "document"}, "nodes": {"role_coordinator": "coordinator"}}`. Read by the service only and ignored by OPA. Without it, identifiers are used |

**3. Graph data.** `hgnn` writes `graph.json` (node identifier → relation → destination identifiers). Generated
rules read it as `data.corax.graph`, so it is copied to `<policy folder>/corax/graph/data.json`. OPA places data
files by folder and merges this one with `data.corax.config`.

### Admin routes

Corax adds these routes itself, so applications do not declare them in `config.routes`. They are served by the
Corax service, and Envoy routes `/corax/` to it.

| Method and path | Action |
|---|---|
| `POST /corax/appeals` | `corax.appeal.create` |
| `GET /corax/appeals/:id` | `corax.appeal.read` |
| `GET /corax/appeals/:id/candidates/:candidate` | `corax.appeal.read` |
| `POST /corax/appeals/:id/confirm` | `corax.appeal.confirm` |
| `POST /corax/appeals/:id/revoke` | `corax.appeal.revoke` |
| `GET /corax/rules` | `corax.rules.read` |
| `GET /corax/me/access` | `corax.me.access`, available to any user with a valid token |
| `GET /corax/suggestions` | `corax.suggestions.read` |
| `POST /corax/rank` | `corax.rank.read` |

Only `config.admin.users` may call them, with the exception of `corax.me.access`, which returns only the caller's
own access. For `corax.*` actions, the application's rules, the rules from appeals and the exceptions are ignored, so
no generated rule can promote a user to administrator. Administrative actions do not invoke the risk check.

### Guarantees

- Identity is derived only from a verified JWT (`sub`). The resource is derived only from the URL path, and the
  query string and body are ignored.
- The AI is consulted only after the policy allows a request, so it can only deny.
- When the risk service fails, times out, or does not know the user or object, the policy decision stands
  (`reason`: `allowed without AI check`).
- Rules from appeals are subject to the risk check. Only the exact pair an administrator approved bypasses it.
- Only listed administrators can create or confirm appeals, and no rule can grant that privilege.
- An allowed request carries the verified user identifier to the upstream service in `x-corax-user`, set by Envoy
  from `result.headers`. The Corax service does not rely on it, because it verifies the administrator's JWT itself.

### Entry points

| Path | Value |
|---|---|
| `corax/authz/allow` | Boolean |
| `corax/authz/allowed_objects` | The subset of `input.objects` that the policy (the application's rules, rules from appeals and exceptions) permits `input.user` to reach with `input.action`, without the risk check. Input is `{"user", "action", "resource_type", "objects"}`. Intended for applications that list only what a user may open, through OPA's API on the internal network |
| `corax/authz/result` | `{"allowed": bool, "headers": {"x-corax-user": "..."}, "dynamic_metadata": {"corax_reason": "...", "corax_risk": 0.12}}`, for opa-envoy-plugin and Envoy access logs |

### Test

```
opa check --strict policy
opa test policy -v
```

## Security

### Invariants

1. `allow = policy_allow AND NOT ai_high_risk`, so the risk score can only turn an allow into a deny.
2. Rules from appeals define only `allow`, only in `app.generated` or `app.exceptions`, and reside only in
   `policies/generated/`.
3. Every rule records its origin, namely its appeal identifier, pattern, scope and tier. The appeal record retains
   the similar cases, the candidates and the history.
4. Access granted by a rule from an appeal remains subject to the risk score. Only the exact pair an administrator
   approved bypasses it.
5. Policies change only through files. OPA's REST API is not used for writes and is not exposed.
6. Every access an appeal grants is recorded at the time of the grant, with who gained access to what and who
   approved it. Every later use is logged, and every revocation through the API is recorded.

### Threats and mitigations

| Threat | Mitigation |
|---|---|
| A socially engineered appeal is generalized | An administrator approves every appeal and selects the pattern. Large rules require a second confirmation |
| Over-generalization | Candidates derive only from the appellant's own attributes, ordered from the narrowest, with the exact users and pairs shown, within the tier limits |
| An incorrect rule from an appeal | An equivalence check against the approved pattern. The risk score still denies pairs that do not fit the graph |
| Graph poisoning [[5]](references.md) | `accessed` edges originate only from allowed requests. The risk score evaluates newly opened pairs (mean risk in the tier) |
| A rule attempts to grant administrator rights or alter other policy | A whitelist permits only `allow` in the two appeal packages, with fixed input and graph references only. `corax.*` actions ignore those packages |
| A non-administrator calls `/corax/appeals` | OPA permits `corax.*` actions only for `config.admin.users`. No application or appeal rule can grant them |
| The service is reached directly, bypassing Envoy and OPA | The service verifies the administrator's JWT itself, with the same key, `iss`, `aud` and administrator list as OPA, read from the same `data.json`, the algorithm fixed by key type, and `exp` and `sub` required. `/risk` must remain on the internal network |
| A forged identity header (`x-corax-user`) | Ignored by the service. The audit log takes the administrator from the verified JWT |
| Rego injection through identifiers in an appeal | Identifiers are written as JSON string literals and appeal identifiers are checked against a fixed pattern. The whitelist rejects any other construct |
| The risk service is down or slow | The policy decision stands (`allowed without AI check`), never an allow beyond the policy |
| Access granted by an appeal is used without oversight | Access is recorded when the administrator accepts it, every use is logged, and every administrator sees both through `GET /corax/rules` |
| A user reads another user's access list | `GET /corax/me/access` derives the user only from the verified token and takes no user parameter |
| Forged usage log entries through `/usage` | `/usage` is internal like `/risk`, only appends to a log for access granted by an appeal, and never affects a decision |

### Scope

**In scope:** Object-level authorization (BOLA), centralized policy as code (ABAC and ReBAC), a risk check that only
tightens decisions, and appeals that turn an administrator's decision into a validated rule.

**Out of scope:**
- Broken Object Property Level Authorization (BOPLA), meaning field-level response filtering and blocking of mass
  assignment.
- Policy changes without human approval.
- Production hardening, such as high availability and multi-cluster deployment.

### Known limitations

- Suggestions and unit rankings rely on design choices (10 peers, half of them with access, risk at most the
  threshold), not on measured values. They support an administrator's decision and never grant access.
- The risk score assesses pairs, not behavior over time. It does not detect rapid enumeration by an otherwise
  legitimate user.
- Hard cases, where a peer holds the object, are detected less often than random ones. See
  [Evaluation](ai-model-and-evaluation.md#evaluation).
- The usage log misses a use when the service is unavailable or slower than `ai.timeout`. A use is attributed to
  the appeal even when the application's own rules would also have allowed it.
- `GET /corax/me/access` lists only access from appeals, not access from the application's own rules.

### Future work

The first three items are the priorities.

1. **More policy languages and gateways:** The graph, the risk score and the appeal flow are independent of Rego
   and of Envoy. Only the rule writer, its validation and the enforcement point are tied to them. Supporting other
   policy languages, such as Cedar or XACML, and other enforcement points, such as Kong, NGINX, Traefik or cloud API
   gateways, would let Corax protect applications that already standardize on them.
2. **Hierarchy depth in the tier:** Organizations often arrange units, sites or categories in a tree. The depth at
   which a rule applies, its distance from the root, indicates how far it reaches. A rule scoped to a team is
   narrower than one scoped to a division. Adding this depth to the tier computation, next to the share of users,
   the new pairs and the mean risk, would separate narrow and broad rules more reliably where such a tree exists.
3. **Lattice-based reasoning alongside the graph:** Candidate rules are currently derived from the graph and
   ordered by the access they open. Arranging attribute combinations in a concept lattice, where each rule
   generalizes the rules below it, would make that ordering explicit. It would let Corax move up or down from an
   approved rule one step at a time, and present the next more general rule together with exactly what it adds.
   Classification levels form a lattice of their own, which would let a rule respect clearance ordering rather than
   individual levels.
4. **Shadow mode for generated rules:** A rule could first run in observation only, recording which requests it
   would allow without allowing them. The administrator would apply it after reviewing real traffic rather than a
   prediction.
5. **Explanations for risk decisions:** The administrator sees a risk score but not its cause. Showing the peers
   and relations that drove a high score, for example that none of the user's closest peers open the object, would
   make AI denials easier to review and dispute.
