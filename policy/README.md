# policy

The Rego framework OPA runs for every request. It is the same for every application that uses Corax:
it verifies the JWT, matches the route, runs the application's own rules, asks the AI for the risk and
applies the deny-only rule.

## Files

| File | Does |
|---|---|
| `request.rego` | Verifies the JWT, matches the method and path to a route, builds the request the rules see |
| `authz.rego` | The decision: policy, admin routes, exceptions, the AI risk check and the reason |
| `authz_test.rego` | Tests, with the service and the application's rules mocked |
| `config.example.json` | Example configuration: JWT, routes, AI address, admins |

## Run

```bash
opa check --strict policy
opa test policy -v
```

What an application provides, the configuration and the guarantees: [docs/reference.md](../docs/reference.md#policy).
