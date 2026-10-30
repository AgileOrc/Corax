# scripts

Helpers around Corax: prepare datasets, evaluate a trained model and run the demo. None of them
trains a model, training happens only through `python -m hgnn`.

## Research

| Path | Does |
|---|---|
| `prepare/` | Turns a dataset into `nodes.csv` and `edges.csv` (dummy data, Amazon, Xu & Stoller) |
| `evaluate/` | Scores a trained model: the risk score and the appeals |
| `demo_risk.py` | Shows the AI's answer next to the true one, on pairs the model never saw |
| `demo_appeal.py` | Runs three appeals end to end and lets OPA decide on the rules they write |
| `similar_cases.py` | Shows the similar cases and candidate rules for one appeal |
| `check_env.py` | Checks that the Python packages are installed |

```bash
python scripts/demo_risk.py --model-dir <model folder>
python scripts/demo_appeal.py --model-dir <model folder> --opa <path to opa>
python scripts/similar_cases.py --model-dir <model folder> --user <user> --object <object>
```

Every script and the commands for each dataset: [docs/scripts.md](../docs/scripts.md#scripts).

## Demo

The scripts of the document app demo ([docs/demo.md](../docs/demo.md)).

| Script | Does |
|---|---|
| `prepare/make_enterprise.py` | Writes a synthetic enterprise graph with nine hidden policies, its `scenarios.json` and the demo's requests, appeals and summary readers (`demo.json`) |
| `prepare/make_office.py` | `generate`: a random office graph per seed, its `scenarios.json` and `cases.json`, with one case for every path of a request (policy deny, AI allow, AI deny, rejected appeal, small and large rules the admin accepts or declines, revoke); `label`: picks the AI cases and checks each rule's tier with the trained model |
| `demo_gateway.py` | Both cases through the Docker gateway of `deploy/`: `prepare` the graph and the HGNN, then `run` requests and appeals via Envoy |
| `demo_office.py` | The cases of `make_office.py` through the Docker gateway of `deploy/`: `prepare --seed N` writes the office, the HGNN and the labelled cases to `output/gateway` (in place of the enterprise), and `accounts.json`, the people of the cases (role and department only) that the web app's sign-in page offers, then `run` takes every case through Envoy as the admin and checks each answer (exit code 1 if one differs) |
| `demo_office_cases.py` | `--count 200`: random cases of the prepared office, every path at least once and none marked, sent through the gateway, printed as traffic in the order things happen (no case numbers; `--quiet` for a counter only) and recorded (request, policy, risk = 1 - sigmoid(h_u . h_d) against the threshold, response, Envoy's reason, the tier's three variables, the Rego written or deleted) in `output/gateway/cases_<count>.json` and `.md`; `cases_<count>_key.json` says which path each case took |
| `demo_backend.py` | 57 cases through the document app of `deploy/` (login, access requests, the admin's decisions), printed as a log with reason, AI risk, tier indicators, generated Rego and OPA's reload time, and checked: a summary at the end, exit code 1 if a case did not show what it should. `--prepared` names another prepared folder |

`prepare` and `demo_backend.py` also run in containers (`docker compose -f deploy/docker-compose.yml run --rm prepare`,
`... run --rm demo`), so the demo needs nothing but Docker.

### The enterprise graph

Employees, teams, departments, sites, regions, projects and documents: 180 employees in 5 departments (3 teams of 12)
and 160 documents. Like courses on a campus, an employee and a document each have two of their department's four
projects, so most employees already read most documents of their department: a department-wide rule opens only the
few documents that share no project with them. Nine hidden policies, each with an appeal and a colleague in the same
situation who never appeals, and two one-off appeals:

| Hidden policy | Pattern | Users, new pairs |
|---|---|---|
| A manager, coordinator, data steward or quality lead (one each per department) reads every document of their department | `user.works_in = object.owned_by AND user holds role_<role>` | 4 or 5, 10 to 19 |
| A security officer reads every document stored in their region | `user.based_in = object.stored_in AND user holds role_security_officer` | 2, 132 |
| A facility manager reads every document stored at their site | `user.located_in = object.stored_at AND user holds role_facility_manager` | 4, 128 |
| An auditor reads every confidential document | `user.cleared_for = object.classified_as` | 2, 47 |
| An HR partner reads every document of the department they support | `user.supports = object.owned_by` | 4, 127 |

Only auditors are cleared and only HR partners support a department, so for those two the role adds nothing and
the pattern miner keeps the single predicate.

```bash
python scripts/demo_gateway.py prepare     # the graph -> output/gateway/data, the HGNN -> output/gateway/hgnn
```

With seed 0 (as `prepare` trains it in Docker: val AUC 0.979, risk threshold 0.968): the four department-role rules rank 1st among the candidate
patterns and are small (mean risk 0.10 to 0.18), so they apply as soon as the admin picks them. The security
officer, facility manager and auditor rules rank 2nd and the HR partner rule 4th; the narrower candidates before
them hold for the appellant alone. All four are large (mean risk 0.92 to 1.00) and need `acknowledge_scope`. The
first candidate of each one-off is large too (12 users; 398 pairs), so it waits for an admin. Over training seeds 0
to 2 every department-role rule stayed small (mean risk at most 0.48) and every other rule stayed large.
