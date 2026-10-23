# deploy

Corax in front of a stand-in campus API with Docker: Envoy → OPA (framework from `policy/` plus the
demo campus rules) → service, on the dummy campus model. Walkthrough and expected output:
[docs/getting-started/full-stack.md](../docs/getting-started/full-stack.md).

```bash
python scripts/prepare/make_dummy.py output/dummy-data
python -m hgnn --data output/dummy-data --target-relation accessed --out output/dummy --learning-rate 0.01 --patience 50
docker compose -f deploy/docker-compose.yml up --build -d
bash deploy/demo/demo.sh
```

| File | Content |
|---|---|
| `docker-compose.yml` | envoy, opa (`opa-envoy-plugin`), service, upstream; volume `generated` shared by service (writes) and opa (`--watch`) |
| `envoy.yaml` | `ext_authz` to OPA over gRPC, `failure_mode_allow: false`; `/corax/*` → service, rest → upstream |
| `service.Dockerfile` | The service plus the `opa` binary it validates Rego with |
| `demo/data.json` | Corax config: demo JWT secret, routes, AI url, admin |
| `demo/app.rego` | The campus rules (teaches / advises; a deliberately broad profile rule) |
| `demo/app_test.rego` | `opa test policy/authz.rego policy/request.rego deploy/demo` |
| `demo/demo.sh` | The seven demo steps with curl |

The JWT secret in `demo/data.json` is for the demo only; production uses `jwt.cert` and tokens from
the identity provider.
