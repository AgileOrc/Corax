# deploy

Corax in front of an application, with Docker:

```
client ──► Envoy :8080 (PEP) ──ext_authz──► OPA + opa-envoy-plugin (PDP: policy/, the application's rules)
              │                                 └─ http.send ──► service /risk (only after the policy allowed)
              ├─ POST /auth/login ──► application (the only route without the check: it issues the token)
              ├─ /corax/...       ──► service /corax/appeals (admins only, JWT checked again)
              │                       ──► exceptions and rules in the "runtime" volume ──► OPA reloads them (--watch)
              ├─ GET /, /assets/  ──► web (the frontend's files, public)
              └─ everything else  ──► application (documents, access requests)
```

This folder only wires the containers together. The demo application, its rules, its frontend and the Corax console
are in [`demo/`](../demo/README.md). Corax itself is `service/`, `policy/` and `hgnn/`.

| File | Content |
|---|---|
| `docker-compose.yml` | The service, OPA, the demo app and its frontend, Envoy (port 8080), console (port 8090); the tools `prepare` and `demo` |
| `envoy.yaml` | Every request goes to OPA first (gRPC `ext_authz`, `failure_mode_allow: false`), except `POST /auth/login`; `/corax/...` (the admin API) → the service, `GET /` and `/assets/` → web, the rest → app |
| `opa.yaml` | opa-envoy-plugin on port 9191, answering with `corax/authz/result`; decision logs on stdout |
| `service.Dockerfile` | The service with the OPA binary, which validates every exception and rule before it is written; creates the `generated/` folder at start, because OPA loads it as soon as it starts |
| `tools.Dockerfile` | Python, CPU torch and the scripts, for `prepare` and `demo` |
| `../demo/data.json` | `data.corax.config`: JWT constraints (demo HS256 secret), the application's routes, the service's URL and timeout, `admin.users` (`admin_01`: the document app has no Corax account of its own). OPA loads it, and the service reads it (`CORAX_CONFIG`) to verify admins itself; the admin routes are built into `policy/request.rego` |
| `../demo/` | The document app, its rules (`policy/`), its web frontend (`web/`) and the Corax console (`console/`): see [demo/README.md](../demo/README.md) |

OPA loads `policy/request.rego` and `policy/authz.rego`, `demo/policy`, `demo/data.json`, the graph exported by `python -m hgnn` (as
`data.corax.graph`) and the runtime folder `generated/`, skipping tests and hidden files (`--ignore=*_test.rego
--ignore=.*`; the service writes each file next to its place under a hidden name and renames it). The service keeps one
record per appeal, with its history, in the `state` volume (`appeals/`), which OPA does not load.

## Run

How to start, configure, reset and troubleshoot the stack: [Getting started](../docs/getting-started.md#deploy-with-docker).
The walkthrough: [Running the demo](../docs/demo.md).

`prepare` and `demo` are one-off services of the profile `tools` (`deploy/tools.Dockerfile`: Python, CPU torch, the
scripts), and `up` does not start them. `demo` mounts the Docker socket to read Envoy's and OPA's logs, which gives it
control of Docker on the machine, so it is a local demo tool.

With Python on the host instead of the tools image ([Getting started](../docs/getting-started.md#develop-without-docker)):

```bash
python scripts/demo_gateway.py prepare     # enterprise graph and HGNN -> output/gateway (1 to 2 minutes)
docker compose -f deploy/docker-compose.yml up -d --build
python scripts/demo_gateway.py run         # requests and appeals through Envoy, a before/after table
python scripts/demo_backend.py             # or: 57 cases through the document app, as a log
```

A second stack on other ports: `CORAX_GATEWAY_PORT=8180 CORAX_CONSOLE_PORT=8190 docker compose -p corax-test -f deploy/docker-compose.yml up -d --build`.
OPA's decisions: `docker compose -f deploy/docker-compose.yml logs opa`.
