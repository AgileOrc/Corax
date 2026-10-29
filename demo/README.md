# demo

The application Corax protects in the demo: a document-management app with its rules, configuration, web frontend
and the Corax console. Nothing here is part of Corax itself. Another application would bring its own versions of
these files. How to run it: [deploy/README.md](../deploy/README.md) and [docs/demo.md](../docs/demo.md).

| Folder or file | Content |
|---|---|
| `app/` | The document app (`docapp/`, FastAPI + SQLite, no authorization of its own) |
| `web/` | Its web frontend (plain HTML, CSS and JavaScript, no build step), served by nginx through Envoy at `/` |
| `console/` | Corax's demo console: you pick who you are, it signs the JWT (it plays the identity provider) and sends the request through Envoy. It also shows the generated Rego and the appeal history |
| `policy/` | The document app's rules (package `app.authz`, `app.rego`) and their tests |
| `data.json` | `data.corax.config`: JWT constraints, the app's routes, the service's address, the admins and readable labels |

## The web frontend

http://localhost:8080 is the document app as people use it (`web/`): sign in, browse and search the catalog, open a
document, preview its summary, and ask for access when Corax denies one. Every request waits for the admin
(`admin_01`): approve (the exact exception applies at once) or reject with a note.
The request then waits under "Your decision" with Corax's candidate patterns, each with its tier (people, new pairs,
mean AI risk): apply one (a large one asks to confirm its scope) or keep only the exception.

Envoy serves `GET /` and `GET /assets/...` from the `web` container without the Corax check, like the login; every
call the page makes goes through Envoy and OPA with the user's token. The page talks only to its own origin (no CORS)
and nginx sends a strict Content-Security-Policy (no inline scripts). The token lives in the tab's `sessionStorage`.

## The document app

`app/docapp` is the application Corax protects: a document-management API (FastAPI, SQLite in the `appdata`
volume). On its first start it seeds the database from the enterprise graph (`output/gateway/data`): one account per
employee and per admin of `demo/data.json`, and the 160 documents, with made-up names, titles and texts. Every
password is `corax-demo` (`CORAX_DEMO_PASSWORD`); the username is the employee number (`e001`) or the id
(`employee_E001`), the admin's is `admin_01`.

The app has no authorization of its own: every route reaches it only when OPA allowed it, with the actions of
`demo/data.json` and the rules of `demo/policy`. It checks the JWT itself only to know who is calling.

| Route | Corax action (resource type) | Who may | |
|---|---|---|---|
| `POST /auth/login` | none (Envoy skips the check) | anyone | `{username, password}` → a JWT signed with the demo secret, the one OPA and the service verify |
| `GET /me` | `profile.read` (profile) | signed in | the account |
| `GET /documents?q=&department=&classification=` | `documents.list` (catalog) | signed in | titles and metadata, no content, of the documents the employee may open only (the app asks OPA's `corax/authz/allowed_objects` on the internal network, and lists nothing if OPA does not answer); admins see every document; `in_my_projects` is only a hint |
| `GET /documents/:id` | `read` (document) | the application's rules, rules from appeals, exceptions; AI check | the document |
| `POST /access-requests/:document` | `access.request` (access_request) | employees | `{reason}` → a `pending` request; no `:id`, so the AI check does not judge the asking. The app does not call Corax: the request waits for an admin |
| `GET /access-requests` | `access.list_own` | signed in | the caller's requests |
| `GET /admin/access-requests?status=` | `access.review` | admins | every request |
| `POST /admin/access-requests/:request/approve` | `access.review` | admins | for a pending request: starts the appeal in Corax (`POST /corax/appeals` through Envoy, with the admin's token): the exact exception at once, and the candidate patterns; `already_granted` when Corax answers that the user can read it already. No pattern is applied: the admin picks one with confirm |
| `POST /admin/grants` | `access.review` | admins | `{user, document, reason}`: gives a document without a request; it starts approved, then the admin picks a rule as for confirm |
| `GET /admin/employees` | `access.review` | admins | every employee, without passwords, for Give access |
| `GET /admin/suggestions`, `POST /admin/suggestions/dismiss` | `access.review` | admins | Corax's suggested access (`GET /corax/suggestions`) with names and titles, without the dismissed ones |
| `GET /units` | `units.list` | signed in | the departments, the employee's own first |
| `POST /unit-requests`, `GET /unit-requests` | `access.request`, `access.list_own` (unit_request) | employees | ask for a whole unit `{unit, reason}`; an employee sees only how many documents were given |
| `GET /admin/unit-requests`, `GET .../:request/documents`, `POST .../:request/grant`, `POST .../:request/reject` | `access.review` | admins | the unit's documents ranked by Corax (`POST /corax/rank`), give the ticked ones, or reject |
| `POST /admin/access-requests/:request/confirm` | `access.review` | admins | for a granted request whose pattern the admin picks: `{candidate, acknowledge_scope}`; a small pattern is written at once, a large one answers 409 with its scope until `acknowledge_scope`; `candidate: null` keeps only the exception |
| `POST /admin/access-requests/:request/reject` | `access.review` | admins | `{note}` |

A request is `generalised` or `already_granted` as soon as it is sent, or `pending`; a pending one moves to
`rejected`, `already_granted`, `generalised` (the exception and a small rule), or `granted` (the exception; the best
pattern was large) → `generalised` (the admin's choice, with its tier) or `exception_only`.

`GET /documents/:id/summary` (action `read_summary`) is deliberately too broad: every employee may read every
summary, so the AI check decides, like the profile route of PR #7's campus demo.

`python scripts/demo_backend.py` runs 57 cases through the app on a fresh stack and prints them as a log, in seven
parts: what the policy allows and denies (BOLA attempts among them); missing, forged and expired tokens, unknown routes
and admin-only routes; the summary route, where the AI check decides (six employees, a usual and an unusual document
each); four access requests whose rule is small (the admin picks it, with no second confirmation); seven whose
best rule is large (the admin declines four and approves three after reviewing the scope); what holds after the
decisions (exceptions skip the AI check, rules do not; repeated, rejected and already readable requests; the appeal's
history); and revoking rules and an exception by deleting their files. Each case is checked against what it should
show; the log ends with a summary of all 57, and the exit code is 1 if one did not. Reason and risk come from Envoy's
access log, the reload time from OPA's log, the Rego from the service's runtime folder. A case looks like this:

```
Case 31: Engineering coordinator asks for an Engineering document (employee_E049, document_D057)
  expect  : generalizes: every coordinator reads the documents of their own department (small rule)
  witness : employee_E085 (Finance coordinator) never asks for access
  before  : GET /documents/document_D070 as employee_E085 -> 403 (denied by policy)
  request : POST /access-requests/document_D057 as employee_E049 -> 201 Created, request #2 pending
  status  : waits for the admin
  request : POST /admin/access-requests/2/approve as admin_01 -> 200 OK, granted
  corax   : POST /corax/appeals -> 201 Created, appeal-0001, exception written
  admin   : picks candidate #1: An employee may read a document when the employee and the document have the same department and the employee is a coordinator.
  request : POST /admin/access-requests/2/confirm {"candidate": 1}
  response: 200 OK, rule_applied
  indicators            value   limit
    users affected          4       5    ok
    new pairs              10      50    ok
    mean risk            0.11    0.50    ok
  tier    : SMALL -> applied with no second confirmation
  policy  : + appeal-0001-rule.rego
              allow if {
                input.action == "read"
                input.resource.type == "document"
                some n1 in data.corax.graph[input.user.id]["works_in"]
                n1 in data.corax.graph[input.resource.id]["owned_by"]
                "role_coordinator" in data.corax.graph[input.user.id]["holds"]
              }
  opa     : reloaded in 57 ms (no restart)
  after   : GET /documents/document_D070 as employee_E085 -> 200 (allowed, risk 0.0271)
```

Try the app with curl:

```bash
TOKEN=$(curl -s -X POST localhost:8080/auth/login -H 'Content-Type: application/json' \
  -d '{"username": "e049", "password": "corax-demo"}' | python -c "import json, sys; print(json.load(sys.stdin)['token'])")
curl -H "Authorization: Bearer $TOKEN" 'localhost:8080/documents?department=engineering'
```

## What the demo shows

The data is the synthetic enterprise of `scripts/prepare/make_enterprise.py`: 180 employees in 5 departments, 160
documents and nine hidden policies (see [scripts/README.md](../scripts/README.md)). `demo_gateway.py run` first sends
the named requests of `demo.json`, then handles the ten appeals as `admin_01` (`POST /corax/appeals`): it confirms
the pattern each scenario expects (`POST /corax/appeals/{id}/confirm`), again with `acknowledge_scope` when the
service answers 409 because the rule is large, and for the two one-off appeals it confirms no pattern
(`candidate: null`). Then it sends the requests again (some of the 26 rows):

```
                                                                                     risk   before appeals  after appeals
Project member reads a document of their project                                     0.065  200             200
Sales analyst reads a confidential Finance document (BOLA)                           0.982  403             403
Engineering coordinator reads an Engineering document                                0.261  403             200
Finance coordinator (never appeals) reads what the rule of the appeal would open     0.027  403             200
Security officer (EMEA) reads a document stored in EMEA                              0.994  403             200
Security officer (APAC) (never appeals) reads what the rule of the appeal would open 0.970  403             403
Auditor reads a confidential document of another department                          1.000  403             200
Other auditor (never appeals) reads what the rule of the appeal would open           1.000  403             403
Engineer reads a confidential document of another project                            0.293  403             200
```

- The four department-role rules (manager, coordinator, data steward, quality lead) are small: 4 or 5 users, 10 to
  19 new pairs, mean risk 0.10 to 0.18, so the service writes them as soon as the admin picks them. The other four
  are large: the security officer, facility manager and HR partner rules open 127 to 132 new pairs, and all four
  have a mean risk of 0.92 to 1.00 (the auditor rule is large by its risk alone: 2 users, 47 pairs). The first
  confirm answers 409 and the rule is written only with `acknowledge_scope`.
- The appellants get their exact exceptions; their colleagues get access through the generated rules, without an
  appeal of their own.
- The one-off appeals kept only their exceptions, so only those pairs are open; the BOLA requests stay denied.
- A pair that a generated rule opens still goes through the AI check: the auditor rule opens confidential documents
  of every department, and the other auditor's request has a risk of 1.000, above the threshold (0.968), so it stays
  denied (`reason`: `high AI risk`); so does the APAC officer's request (0.970) under the security officer rule. The
  appellants' own requests pass, though their risk is as high: exceptions skip the check. These numbers come from the
  model `prepare` trains in Docker; another PyTorch build gives slightly different ones.
- `POST /corax/appeals` by anyone but an admin is refused at the gateway (403); called directly, the service refuses it
  too (401 without a valid token, 403 for a non-admin).
