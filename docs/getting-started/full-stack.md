# Full stack with Docker

Real requests through Envoy, OPA and the service, on dummy data. Unlike the
[Quick start](quickstart.md) scripts, this shows the deny-only AI check on live requests and OPA loading
a rule from an appeal without a restart.

<!-- TODO image: client → Envoy :8080 → OPA → service; Envoy → application; Envoy /corax/* → service; service → rules → OPA -->
![Full stack](../assets/full-stack.png)

| Container | Role | Port |
|---|---|---|
| `envoy` | Gateway: asks OPA about every request, forwards the allowed ones | `8080`, the only one published |
| `opa` | Policy engine: Corax's framework, the application's rules and the rules from appeals | internal |
| `service` | `/risk` for OPA, `/corax/appeals` for admins | internal |
| `upstream` | Stand-in for the protected application (answers every allowed request) | internal |

The service and OPA share a volume for the rules from appeals, and OPA watches it (`--watch`), so a new
rule is live without a restart. Both run inside Linux, so the file events reach OPA; a folder on Windows
bind-mounted into a container often does not deliver them.

## Run

Needs Docker and the trained dummy model from the [Quick start](quickstart.md) (`output/dummy`). From
the repository root:

```bash
docker compose -f deploy/docker-compose.yml up --build -d
```

```bash
bash deploy/demo/demo.sh
```

`demo.sh` needs only `docker` and `curl`: it signs the demo tokens and reads JSON with the Python inside
the service container. For your own requests, `scripts/make_token.py --sub <user>` prints a token.

The script starts from no appeals and stops if rules from an earlier run are still loaded. To start
again, remove the volumes:

```bash
docker compose -f deploy/docker-compose.yml down -v
```

## The demo application

`deploy/demo/app.rego` holds the application's own rules, evaluated by Corax's framework in `policy/`:

| Route | Rule |
|---|---|
| `GET /students/:id/grades` | Allowed when the user is directly related to the object (teaches or advises them) |
| `GET /students/:id/profile` | **Deliberately too broad**: every staff user |

## What the demo shows

The script prints one block per case, in three sections:

| Case | What happens | Expected |
|---|---|---|
| **A. Denied by policy** | | |
| 1 | A user requests an object they have no relation to | **403**, `denied by policy`; the AI is not asked |
| **B. Allowed by policy, checked by Corax** | | |
| 2 | Through the over-broad rule, a user requests an object that fits their access pattern | **200**, risk far below the threshold |
| 3 | Through the same rule, the same user requests an object that does not fit | **403**, `high AI risk`: the policy allows it, the AI denies it |
| **C. Appeals** | | |
| 4 (small) | An admin approves one user's appeal; the chosen rule is small | Applied at once; another user in the same situation, who never appealed, goes from **403** to **200** |
| 5 (large, declined) | An appeal whose chosen rule is large | **409**, waits for the admin; the admin keeps only the exact exception, so other pairs stay **403** |
| 6 (large, approved) | Another large appeal | **409**, then approved with `acknowledge_scope`; another user who never appealed goes from **403** to **200** |
| 7 (revoke) | The rule file of case 6 is deleted | OPA reloads; that user is **403** again. This is how a rule from an appeal is rolled back |

For every request the script shows the response and OPA's reason, and in section B the threshold and
the AI risk. For every appeal it shows the three tier indicators against their limits, the tier, the
`allow` block of the Rego file that was written, and how long OPA took to load it. Case 4 looks like
this (the ids come from the dummy data):

```
Case 4 (small): lecturer_head_P0 appeals to access student_P0_05, then the admin accepts
  before  : GET /students/student_P2_14/grades as lecturer_head_P2 -> 403 (denied by policy)
  request : POST /corax/appeals -> 201 Created, appeal-0001, exception written
            candidate #2: user.member_of = object.member_of AND user holds position_head_of_program
  request : POST /corax/appeals/appeal-0001/confirm {"candidate": 2}
  response: 200 OK, rule_applied
  indicators             value   limit
    users affected     6 (20%)     40%    ok
    new pairs               45      50    ok
    mean risk             0.25    0.50    ok
  tier    : SMALL -> applied without a second confirmation
  policy  : + appeal-0001-rule.rego
              allow if {
                input.action == "read_grades"
                some n1 in data.corax.graph[input.user.id]["member_of"]
                n1 in data.corax.graph[input.resource.id]["member_of"]
                "position_head_of_program" in data.corax.graph[input.user.id]["holds"]
              }
  opa     : reloaded in 15 ms (no restart)
  after   : GET /students/student_P2_14/grades as lecturer_head_P2 -> 200 (allowed, risk 0.2195)
```

The ids in `demo.sh` fit `output/dummy` trained as in the Quick start. Another model may give other
risks; check a pair first with `scripts/similar_cases.py` or `scripts/demo_risk.py`.

## Check the configuration without Docker

```bash
opa test policy/authz.rego policy/request.rego deploy/demo
```

Runs the demo application's rules through the framework with the demo config and a mocked service.
