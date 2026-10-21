# policy

Generic Rego framework shared by every application that uses Corax (package `corax.authz`).

```
Envoy ext_authz input
  1. verify the JWT                      → user.id = sub
  2. match method + path to a route      → action, resource {type, id, ...}
  3. exception_allow = data.app.exceptions.allow  (the exact pair an admin approved in an appeal)
     policy_allow    = data.app.authz.allow       (the application's rules)
                    OR data.app.generated.allow   (rules added through appeals)
  4. ai_high_risk = POST ai-corax /risk            (only when policy_allow and not an exception)
  5. allow = exception_allow OR (policy_allow AND NOT ai_high_risk)
```

| File | Content |
|---|---|
| `corax/request.rego` | JWT verification, route matching, the normalised `request` |
| `corax/authz.rego` | `allow`, the AI risk check, `reason`, and `result` for opa-envoy-plugin |
| `corax/admin.rego` | The admin API of ai-corax (`/appeals`): allowed only for `config.admins` |
| `corax/authz_test.rego` | Tests; ai-corax and the application's rules are mocked |
| `config.example.json` | Example configuration |

## What an application provides

**1. Rules** in package `app.authz` that define `allow`. Their `input` is the normalised request,
never the raw Envoy input:

```json
{
  "user": {"id": "lecturer_budi"},
  "action": "read_grades",
  "resource": {"type": "student", "id": "student_candra", "course_code": "IF201"}
}
```

Appeals write two kinds of files to `policies/generated/`, both defining `allow`:

| Package | Content | AI risk check |
|---|---|---|
| `app.exceptions` | Only the exact (user, action, object) the admin approved | Skipped: the admin reviewed it |
| `app.generated` | The broader rule mined from similar cases | Yes |

**2. Configuration** under `data.corax.config` (see `config.example.json`):

| Key | Meaning |
|---|---|
| `jwt` | Constraints for `io.jwt.decode_verify`: `secret` (HS256, demo) or `cert` (JWKS / PEM, production), plus `iss` and `aud`. `exp` and `nbf` are always checked |
| `routes` | `method`, `path` with `:name` parameters, `action`, `resource_type`. Exactly one route must match, otherwise the request is denied. The `:id` parameter is the object sent to ai-corax |
| `ai.url`, `ai.timeout` | ai-corax address and `http.send` timeout (default `20ms`). Without `ai`, no risk check is made |
| `admins` | User ids (JWT `sub`) allowed to call the admin routes. Without it, nobody can |

**3. Graph data.** `hgnn-job` writes `graph.json` (node id → relation → destination ids).
Generated rules read it as `data.corax.graph`, so copy it to `<policy folder>/corax/graph/data.json`;
OPA places data files by folder and merges it with `data.corax.config`.

## Admin API (ai-corax `/appeals`)

The appeal endpoints are routes like any other, with one of the actions of `admin.rego`:

```json
{"method": "POST", "path": "/appeals", "action": "submit_appeal", "resource_type": "appeal"},
{"method": "GET", "path": "/appeals/:id", "action": "read_appeal", "resource_type": "appeal"},
{"method": "POST", "path": "/appeals/:id/pick", "action": "pick_candidate", "resource_type": "appeal"},
{"method": "POST", "path": "/appeals/:id/confirm", "action": "confirm_appeal", "resource_type": "appeal"},
{"method": "POST", "path": "/appeals/:id/reject", "action": "reject_appeal", "resource_type": "appeal"}
```

A request on such a route is allowed only when the token's user is in `config.admins` (`reason`: `allowed admin
request`, otherwise `admin only`). The application's rules, generated rules and exceptions are never asked for these
routes, and there is no AI check. An example configuration is `deploy/corax-config.json`.

## Guarantees

- Identity comes only from a verified JWT (`sub`). The resource comes only from the URL path; the query string and body are ignored.
- The AI is asked only after the policy allowed the request, so it can only deny.
- If ai-corax errors, times out, or does not know the user or object, the policy decision stands (`reason`: `allowed without AI check`).
- Rules from appeals also go through the AI risk check; only the exact pair an admin approved skips it.
- Only `config.admins` reach the admin API; no application or generated rule can open it.

## Entry points

| Path | Value |
|---|---|
| `corax/authz/allow` | boolean |
| `corax/authz/result` | `{"allowed": bool, "dynamic_metadata": {"corax_reason": "...", "corax_risk": 0.12}}`, for opa-envoy-plugin and Envoy access logs |

## Test

```
opa check --strict policy
opa test policy -v
```
