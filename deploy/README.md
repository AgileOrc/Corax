# deploy

Corax in front of an application, with Docker:

```
client ──► Envoy :8080 (PEP) ──ext_authz──► OPA + opa-envoy-plugin (PDP: policy/corax, the application's rules)
              │                                 └─ http.send ──► ai-corax /risk (only after the policy allowed)
              ├─ /documents/... ──► application
              └─ /appeals...    ──► ai-corax (admins only) ──► exceptions and rules in the "runtime" volume
                                                               ──► OPA reloads them (--watch)
```

The application is a demo document store with its own rules (`demo-app/`); `console/` is a web page to try it. Both
are demo only and can move to the Corax-Demo repository; the rest is what any application needs.

| File | Content |
|---|---|
| `docker-compose.yml` | ai-corax, OPA, the demo app, Envoy (port 8080), console (port 8090) |
| `envoy.yaml` | Every request goes to OPA first (gRPC `ext_authz`, `failure_mode_allow: false`); `/documents/...` → app, `/appeals...` → ai-corax |
| `opa.yaml` | opa-envoy-plugin on port 9191, answering with `corax/authz/result`; decision logs on stdout |
| `corax-config.json` | `data.corax.config`: JWT constraints (demo HS256 secret), routes including the admin routes, ai-corax URL and timeout, admins |
| `ai-corax.Dockerfile` | ai-corax with the OPA binary, which validates every exception and rule before it is written |
| `demo-app/` | The document store (no access control of its own) and its rules in `policy/` (package `app.authz`, with tests) |
| `console/` | Demo web page: you pick who you are, it signs the JWT (it plays the identity provider) and sends the request through Envoy |

OPA loads `policy/corax`, `demo-app/policy`, `corax-config.json`, the graph exported by `hgnn-job` (as
`data.corax.graph`) and the runtime folder `generated/`, skipping tests and hidden files (`--ignore=*_test.rego
--ignore=.*`; ai-corax writes each file next to its place under a hidden name and renames it). ai-corax keeps the
appeal states and `audit.jsonl` in the `state` volume, which OPA does not load.

## Run

```bash
python scripts/demo_gateway.py prepare     # enterprise graph and HGNN -> output/gateway (about 1 minute)
docker-compose -f deploy/docker-compose.yml up -d --build      # or: docker compose ...
python scripts/demo_gateway.py run         # both cases through Envoy; prints a before/after table
# the console: http://localhost:8090
docker-compose -f deploy/docker-compose.yml down -v             # -v also drops exceptions and rules
```

Other ports: `CORAX_GATEWAY_PORT=8180 CORAX_CONSOLE_PORT=8190 docker-compose -p corax-test -f deploy/docker-compose.yml up -d --build`.
OPA's decisions: `docker-compose -f deploy/docker-compose.yml logs opa`.

## What the demo shows

The data is the synthetic enterprise of `scripts/make_enterprise.py`: 96 employees in 4 departments, 96 documents,
two hidden policies (managers read their department's documents; security officers read the documents stored in their
region). `demo_gateway.py run` first sends the named requests of `demo.json`, then handles three appeals as `admin_01`:
it picks the pattern each scenario expects, confirms it when the tier is large, and rejects the engineer's one-off
appeal. Then it sends the requests again:

```
                                                             risk   before appeals  after appeals
Project member reads a document of their project             0.046  200             200
Sales manager reads a Sales document outside their projects  0.268  403             200
Engineering manager reads an Engineering document            0.856  403             200
Security officer (EMEA) reads a document stored in EMEA      0.957  403             200
Security officer (APAC) reads a document stored in APAC      0.988  403             200
Engineer reads a confidential document of another project    0.916  403             200
Sales analyst reads a confidential Finance document (BOLA)   0.995  403             403
```

- The Sales manager, the EMEA officer and the engineer get their exact exceptions; the Engineering manager and the
  APAC officer get access through the generated rules, without an appeal of their own.
- The engineer's appeal was rejected, so only that one pair is open; the BOLA request stays denied.
- A pair that a generated rule opens still goes through the AI check: of the 77 pairs the security officer rule
  opens, 15 have a risk above the threshold (0.995) and stay denied (`reason`: `high AI risk`). Exceptions skip it.
- `POST /appeals` by anyone but an admin is refused at the gateway (403).
