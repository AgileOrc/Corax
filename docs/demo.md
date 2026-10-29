# Running the demo

Everything runs in Docker: after cloning the repository you need nothing else. This guide sets the demo up, then
walks through each way to try it:

1. [Before you start](#1-before-you-start)
2. [Set up (once)](#2-set-up-once)
3. [Demo 1: the 57 cases as a log](#3-demo-1-the-57-cases-as-a-log) (automatic, about a minute)
4. [Demo 2: the Document Hub by hand](#4-demo-2-the-document-hub-by-hand) (the web app, as employees and the admin)
5. [Demo 3: the Corax console](#5-demo-3-the-corax-console)
6. [Demo 4: the before/after table](#6-demo-4-the-beforeafter-table)
7. [Reset, stop, clean up](#7-reset-stop-clean-up)
8. [Settings](#8-settings)
9. [Without Docker: tests and scripts](#9-without-docker-tests-and-scripts)
10. [Troubleshooting](#10-troubleshooting)

**What you are looking at.** A document-management app with 180 employees in 5 departments and 160 documents. The
app has no access checks of its own: every request goes through Envoy, OPA decides with Rego rules, and Corax's AI
denies requests the rules allow but that don't fit the access graph. When an employee is denied a document they can
ask for access, and the admin decides. Corax suggests a rule that would also cover people in the same situation: one
that reaches few people applies as soon as the admin picks it, one that reaches many needs a second confirmation. All
data is synthetic.

```
browser ──► Envoy :8080 ──► OPA (Rego rules + rules from appeals) ──► AI risk check (the service)
               ├─ /corax/...  ──► the service: appeals, rules written as .rego files, OPA reloads them
               └─ the rest    ──► the document app (FastAPI + SQLite), the web frontend (nginx)
```

## 1. Before you start

- **Docker**: Docker Desktop (Windows, macOS) or Docker Engine with the compose plugin (Linux). Check with
  `docker compose version`. With the older standalone tool, write `docker-compose` wherever this guide says
  `docker compose`.
- **Free ports** 8080 (the app) and 8090 (the console), or choose others ([Settings](#8-settings)).
- **About 2.5 GB of disk** for the images (most of it is PyTorch, used once to train the model).
- Run every command **from the repository root**. They are the same in PowerShell, cmd and macOS/Linux terminals.

## 2. Set up (once)

```bash
git clone https://github.com/AgileOrc/Corax.git
cd Corax
docker compose -f deploy/docker-compose.yml run --rm prepare
docker compose -f deploy/docker-compose.yml up -d --build
```

- `prepare` builds the tools image (the first time takes a few minutes), generates the synthetic enterprise into
  `output/gateway/data` and trains the graph model into `output/gateway/hgnn` (about 20 seconds). You run it once;
  `output/` stays on your disk.
- `up -d --build` builds and starts six containers: `envoy` (the gateway, port 8080), `opa` (the policy), `service`
  (Corax: AI risk check and appeals), `app` (the documents API), `web` (the frontend) and `console` (port 8090).

Check that everything is up (`app` and `service` should say `healthy`):

```bash
docker compose -f deploy/docker-compose.yml ps
```

Then open **http://localhost:8080** (the Document Hub) and **http://localhost:8090** (the Corax console).

> Tip: to drop `-f deploy/docker-compose.yml` from every command, set `COMPOSE_FILE` once per terminal:
> `export COMPOSE_FILE=deploy/docker-compose.yml` (macOS/Linux), `$env:COMPOSE_FILE="deploy/docker-compose.yml"`
> (PowerShell) or `set COMPOSE_FILE=deploy/docker-compose.yml` (cmd).

**Each demo changes the stack** (requests, exceptions, rules). Start each one from a fresh stack; resetting takes a
few seconds and keeps the prepared data:

```bash
docker compose -f deploy/docker-compose.yml down -v
docker compose -f deploy/docker-compose.yml up -d
```

## 3. Demo 1: the 57 cases as a log

```bash
docker compose -f deploy/docker-compose.yml run --rm demo
```

It plays 57 cases through the app, the way people use it, and prints each one with what happened at every step:
the HTTP requests, OPA's reason, the AI risk, Corax's candidate rule and its scope, the Rego that was written and
how fast OPA reloaded it. Add `> demo-log.txt` to keep it in a file.

| Part | Cases | What happens |
|---|---|---|
| 1 | 1–8 | Employees read documents: their projects, public documents of their department, BOLA attempts |
| 2 | 9–18 | No token, a forged admin token, an expired one, an unknown user, a route that does not exist, admin-only routes, a wrong password |
| 3 | 19–30 | Every employee may preview every summary (a rule that is too broad), so the AI decides: a usual document passes, an unusual one is denied |
| 4 | 31–34 | Small rules: the admin approves and picks the rule, which applies with no second confirmation; a colleague who never asked gets access too |
| 5 | 35–41 | Large rules: the request waits for the admin, who declines (only that one document) or reviews the scope and approves |
| 6 | 42–52 | After the decisions: exceptions skip the AI check, rules do not; repeated, rejected and already readable requests; an appeal's history |
| 7 | 53–57 | Rules and an exception are revoked by deleting their files |

A case looks like this:

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
              allow if { ... "role_coordinator" in data.corax.graph[input.user.id]["holds"] }
  opa     : reloaded in 52 ms (no restart)
  after   : GET /documents/document_D070 as employee_E085 -> 200 (allowed, risk 0.0271)
```

The log ends with a summary of all 57 cases, `ok` or `FAIL`, and the command exits with code 1 if a case did not show
what it should. On a stack that was used before, cases fail: reset it first. The `demo` container reads Envoy's and
OPA's logs through the Docker socket, so it is a tool for your own machine only.

## 4. Demo 2: the Document Hub by hand

Open **http://localhost:8080** on a fresh stack. Every password is **`corax-demo`**; the username is `e` and the
employee number (`e049`), and the admin is `admin_01`. The sign-in page lists a few accounts to click.

| Account | Who | Used in |
|---|---|---|
| `e040` | Hugo Koch, Engineer, Engineering | 4.1, 4.2, 4.4 |
| `e049` | Putri Setiawan, Coordinator, Engineering | 4.3 |
| `e085` | Yusuf Koch, Coordinator, Finance | 4.3, 4.7 |
| `e001` / `e037` | Greta Lim, Manager, Sales / Iris Nugroho, Manager, Engineering | 4.3 |
| `e097` / `e169` | Tono Santoso, Data steward, Finance / Lotte Pratama, Data steward, HR | 4.3 |
| `e110` / `e002` | Eko Smit, Quality lead, Operations / Citra Nugroho, Quality lead, Sales | 4.3 |
| `e111` | Milan Setiawan, Security officer, Operations (EMEA) | 4.4 |
| `e003` | Ana Hartono, Analyst, Sales | 4.5 |
| `admin_01` | Corax admin: reviews access requests | 4.4, 4.5 |

The current rules let an employee read a document **in one of two ways**: they work on one of its projects, or it is a
*public* document of their own department. Nothing else, whatever their role.

### 4.1 The policy decides

1. Sign in as **`e040`**. **Documents** lists only the documents `e040` may open: the titles of the others are never
   shown. Try the search box and the department filter.
2. Open **D033**: allowed (`e040` works on one of its projects).
3. Change the id in the address bar to **D130**, a confidential HR document: **No access**, with no title or details.
   An id that does not exist, such as **D999**, looks exactly the same, so nobody can tell which documents exist.
   That is the BOLA attack the gateway stops.

### 4.2 The AI check

Previews are deliberately too broad: every employee may preview every document, so the policy allows them all and
the AI risk check decides.

1. Still as **`e040`**, click **Preview** on **D040**: the summary is shown (a usual request for this engineer).
2. Click **Preview** on **D133**: **Corax blocked this preview** (unlike anything people like `e040` read).

### 4.3 Small rules: one confirmation

An employee asks for a document of their own department that shares no project with them. The request waits for the
admin. After the admin approves, Corax suggests a rule for people in the same situation: one person per department
holds the role, so it reaches **few people** (at most 5 people, 50 new pairs and a mean AI risk of 0.5), and it applies
as soon as the admin picks it, with no second confirmation.

| # | Sign in as | Ask for | The rule the admin picks | Colleague who never asks: before → after |
|---|---|---|---|---|
| 1 | `e049` Engineering coordinator | **D057** | Coordinators read the documents of their own department | `e085` opens **D070** |
| 2 | `e001` Sales manager | **D011** | Managers read the documents of their own department | `e037` opens **D057** |
| 3 | `e097` Finance data steward | **D074** | Data stewards read the documents of their own department | `e169` opens **D137** |
| 4 | `e110` Operations quality lead | **D101** | Quality leads read the documents of their own department | `e002` opens **D003** |

Scenario 1, step by step:

1. **Before**: sign in as **`e085`**, open **D070** by its link (`#/documents/document_D070`): "No access". Sign out.
2. Sign in as **`e049`**, open **D057** by its link (a colleague shared it), write a reason ("I coordinate all engineering projects") and click
   **Request access**: "Request sent … waiting for an admin".
3. Sign in as **`admin_01`**. Under **Pending**, click **Approve**: `e049` can read D057 now. Corax lists its
   suggestions for people in the same situation. Click **Who would gain access** next to the coordinator one to see
   the 4 people and their documents, then **Give access**: it applies at once, with no second confirmation.
4. **After**: sign in as **`e085`** again. **Documents** shows a banner, "new documents were shared with you", and
   **Shared with me** lists **D070** with a **New** badge: open it, **Corax allowed it**, although `e085` never asked.
   `e049` sees only **Access granted** for D057, never the rule.
5. Sign in as **`admin_01`** and open **Access granted**: the rule in plain language, who approved it, the 4 people
   who gained access and to which documents, and the line "e085 read D070" from step 4.

The other three work the same way. `e001`, for example, can then also open D012, D017 and D018: the rule covers every
Sales document, not only the one asked for.

### 4.4 Large rules: the admin decides

When the best rule would open too much (more than 5 people, more than 50 new pairs, or a mean AI risk above 0.5), the
admin sees it before choosing and has to confirm it a second time.

**Decline: only that one document.**

1. Sign in as **`e040`**, open **D037** (a confidential document of another project) and click **Request access**:
   "Request sent … waiting for an admin".
2. Sign in as **`admin_01`**. Under **Pending**, click **Approve**: `e040` gets this one document at once (an exact
   exception), and the page shows Corax's suggestions, narrowest first, each in plain words. They all reach many
   people.
3. Click **Only this person**.
4. Sign in as **`e040`**: **D037** opens, but another document of the department, such as **D036**, is still denied.

**Approve a large rule after reviewing it.**

1. Sign in as **`e111`** (security officer, EMEA), open **D007** and click **Request access**: it waits (the request
   is unusual, and the rule would be large).
2. As **`admin_01`**: **Approve**. Before choosing, **Who would gain access** next to each candidate lists the people
   and documents it would open, without writing anything. Then click **Apply** next to candidate **#2**,
   `user.based_in = object.stored_in AND user holds role_security_officer` (security officers read what is stored in
   their region).
3. Corax answers **Large scope: Corax asks you to confirm**, with the numbers (132 new pairs, mean risk 0.97) and
   the first people who would gain access. Click **Confirm large scope**: the rule is applied.
4. The AI check still applies to every pair the rule opens: unusual ones stay denied.

More requests that wait for the admin: `e125` (facility manager, Jakarta) asks for **D001**, `e076` (auditor) for
**D029**, `e171` (HR partner) for **D034**, `e147` (HR analyst) for **D001**.

### 4.5 Reject with a note

1. Sign in as **`e003`** (Sales analyst), open **D073** (a Finance document) and click **Request access**: it waits.
2. As **`admin_01`**: **Reject**, write a note ("Finance documents are for Finance"), confirm.
3. As **`e003`**: **My requests** shows the rejection and the note; D073 stays denied.

### 4.6 What the admin sees

Signed in as **`admin_01`**, **Access requests** has four tabs: **Pending**, **Your decision** (approved requests
whose rule still needs a choice), **Decided**, and **All**. Admins do not read
documents: opening one as `admin_01` is denied.

**Access granted** lists every rule and exception an admin approved that is still in effect:
the rule in plain language, who approved it and when, who gained access to which documents, and every time that
access was used since. Every admin sees the same list, so nobody has to ask who opened what.

### 4.7 Revoke a rule

As `admin_01`, open the request (or **Access granted**) and click **Revoke the rule**: Corax deletes the rule's
`.rego` file, records who revoked it and when, and OPA reloads within milliseconds. **Revoke all access** also takes
back the employee's own exception.

After scenario 1 of 4.3 (`appeal-0001`), `e085` is denied **D070** again, and D070 disappears from their **Shared
with me**.

Deleting the file by hand also revokes the rule, but nothing records it, and **Access granted** flags the rule as
"file missing":

```bash
docker compose -f deploy/docker-compose.yml exec service rm /runtime/generated/appeal-0001-rule.rego
```

### 4.8 Access without asking

A user cannot ask for what they cannot see. So access can also start from the admin, and the employee never learns
which documents exist until one is given.

**The admin gives access.** As `admin_01`, open **Give access**, choose an employee and a document (for example
someone who just joined a team) and say why. The employee can open it at once, and Corax suggests the same access for
people in the same situation, as for an approved request.

**Corax suggests access.** As `admin_01`, open **Suggested access**: documents Corax expects an employee needs but
nobody gave yet, because most of the 10 people most like them can open it and the request would look normal.
**Give access** follows the same steps as above. **Dismiss** hides a suggestion. The employee never sees this list.

**An employee asks for a unit.** As an employee, open **Ask for a unit**, choose a department from the list (never
typed, never a document title) and say what you need, for example "the grant budget of my program". As `admin_01`,
**Unit requests** → **Decide** shows that department's documents the employee cannot open yet, ranked by Corax for
them, with a warning when nobody like them opens anything there. Tick the ones to give: each becomes an approved
request, and the employee sees how many were shared under **Shared with me**, never the rest of the unit.

## 5. Demo 3: the Corax console

**http://localhost:8090** shows Corax itself, without the document app. It plays the identity provider: you pick who
you are, and it signs the token.

1. **Sign in as**: an admin or an employee, grouped by role.
2. **Read a document**: the request goes through Envoy and OPA; you see allowed or denied, OPA's reason and the AI
   risk.
3. **Approve an appeal** (as the admin): the exact exception, then the candidate rules; pick one, confirm a large
   scope, or keep only the exception.
4. **Policy added on top of the application rules** and **Corax activity**: the generated Rego files and every
   appeal's history.

## 6. Demo 4: the before/after table

On a fresh stack:

```bash
docker compose -f deploy/docker-compose.yml run --rm demo scripts/demo_gateway.py run --gateway http://envoy:8080
```

It sends 26 named requests, handles the ten appeals as the admin directly through Corax's API (each with the rule
it expects), and sends the requests again. It prints a table with each request's AI risk and its answer before and
after the appeals: the appellants and their colleagues go from 403 to 200, the BOLA attempts stay 403, and pairs that
a rule opens but the AI finds unusual stay 403.

## 7. Reset, stop, clean up

| What | Command |
|---|---|
| Start again from a fresh stack (drops requests, exceptions and rules, keeps the prepared data) | `docker compose -f deploy/docker-compose.yml down -v`, then `... up -d` |
| Stop, keeping everything | `docker compose -f deploy/docker-compose.yml down`, later `... up -d` |
| Remove the containers, volumes and images | `docker compose -f deploy/docker-compose.yml down -v --rmi local`, and `docker image rm corax-tools` |
| Generate the data and train the model again | delete `output/gateway`, then `... run --rm prepare` |

## 8. Settings

Set these in the terminal before `up` (PowerShell: `$env:NAME="value"`; cmd: `set NAME=value`; bash:
`export NAME=value`), then run `up -d` again.

| Variable | Default | Meaning |
|---|---|---|
| `CORAX_GATEWAY_PORT` | `8080` | Port of the Document Hub |
| `CORAX_CONSOLE_PORT` | `8090` | Port of the console |
| `CORAX_DEMO_PASSWORD` | `corax-demo` | Every account's password; set it before the first `up` (or reset), the app seeds its accounts once |

The limits of a small rule (6% of the model's 86 employees, so 5 people, then 50 new pairs and mean risk 0.5) are
the service's `AUTO_APPLY_MAX_USER_SHARE`, `AUTO_APPLY_MAX_PAIRS` and `AUTO_APPLY_MAX_MEAN_RISK`. The share is set
under `service:` → `environment:` in `deploy/docker-compose.yml`. Add or change them there, then `up -d`.

## 9. Without Docker: tests and scripts

For development, with Python 3.11 or newer and the [OPA binary](https://www.openpolicyagent.org/docs/latest/#running-opa):

```bash
python -m venv .venv                       # then activate it
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r hgnn/requirements.txt -r service/requirements.txt -r demo/app/requirements.txt -r requirements-dev.txt
pytest                                     # set OPA_PATH if opa is not on the PATH
opa test policy demo/policy
python scripts/demo_gateway.py prepare     # the same as "run --rm prepare"
```

`python scripts/demo_backend.py` runs Demo 1 from the host; it needs the `docker` command to read the containers'
logs. More detail: [deploy/README.md](../deploy/README.md) (the stack and the app's routes),
[scripts/README.md](../scripts/README.md) (the synthetic enterprise and its hidden rules),
[service/README.md](../service/README.md) and [policy/README.md](../policy/README.md).

## 10. Troubleshooting

| Problem | Fix |
|---|---|
| `port is already allocated` | Another program uses 8080 or 8090: choose other ports ([Settings](#8-settings)) |
| Demo 1 says "the stack has N generated file(s) already", or cases fail | The stack was used before: reset it ([section 7](#7-reset-stop-clean-up)) |
| A scenario of 4.3 shows the colleague allowed before | It works once per stack: the colleague may already have access. Reset |
| The containers stopped after Docker or the computer restarted | `docker compose -f deploy/docker-compose.yml up -d` (the data is kept) |
| The app or the service never becomes `healthy` | `prepare` did not run, or `output/gateway` is missing: run it, then `up -d` |
| You changed `demo/data.json` or `deploy/envoy.yaml` | `docker compose -f deploy/docker-compose.yml restart opa envoy`: both are mounted as single files, which they do not reload |
| Linux: `output/` belongs to root after `prepare` | `sudo chown -R "$USER" output` |
| Your numbers differ slightly from this guide | Training depends on the machine's PyTorch build; the 57 cases still check what each one should show |
