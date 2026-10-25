# deploy

Runs Corax with Docker in front of a stand-in application: Envoy asks OPA about every request, OPA asks
the service for the risk, and admins handle appeals through the same gateway.

## Files

| File | Does |
|---|---|
| `docker-compose.yml` | Starts Envoy, OPA, the service and the stand-in application. The service and OPA share a volume for the rules from appeals |
| `envoy.yaml` | Envoy: sends every request to OPA, denies everything if OPA is down, routes `/corax/*` to the service |
| `service.Dockerfile` | Image of the service, with the `opa` binary it uses to check Rego |
| `demo/data.json` | Demo configuration: JWT secret, routes, AI address, admin |
| `demo/app.rego` | The demo application's own rules |
| `demo/app_test.rego` | Tests of those rules through Corax's framework |
| `demo/demo.sh` | The demo: seven cases with curl |

## Run

From the repository root, after training the dummy model ([getting started](../docs/getting-started.md)):

```bash
docker compose -f deploy/docker-compose.yml up --build -d
bash deploy/demo/demo.sh
```

What the demo shows and the expected output: [docs/getting-started.md](../docs/getting-started.md#3-end-to-end-demo-with-docker).

The JWT secret in `demo/data.json` is for the demo only. Production uses `jwt.cert` and tokens from the
identity provider.
