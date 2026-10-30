# Running the demo

A guided tour of Corax in front of a document app. Start the stack first ([Getting started](getting-started.md)),
then try it in any of these ways:

1. [The 57 cases as a log](#1-the-57-cases-as-a-log) (automatic, about a minute)
2. [The document app by hand](#2-the-document-app-by-hand) (the web app, as employees and the administrator)
3. [The Corax console](#3-the-corax-console)
4. [The before and after table](#4-the-before-and-after-table)

**What you are looking at.** A document-management app with 180 employees in 5 departments and 160 documents. The
app has no access checks of its own. Every request goes through Envoy, OPA decides with Rego rules, and Corax's AI
denies requests the rules allow but that do not fit the access graph. When an employee is denied a document, they can
ask for access, and an administrator decides. Corax then suggests a rule that would also cover people in the same
situation. A narrow rule applies as soon as the administrator picks it, a broad one needs a second confirmation. All
data is synthetic.

```
browser ──► Envoy :8080 ──► OPA (Rego rules + rules from appeals) ──► AI risk check (the service)
               ├─ /corax/...  ──► the service: appeals, rules written as .rego files, OPA reloads them
               └─ the rest    ──► the document app (FastAPI + SQLite), the web frontend (nginx)
```

**Each demo changes the stack** (requests, exceptions, rules). Start each one from a fresh stack. Resetting takes a
few seconds and keeps the prepared data:

```bash
docker compose -f deploy/docker-compose.yml down -v
docker compose -f deploy/docker-compose.yml up -d
```

## 1. The 57 cases as a log

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
| 3 | 19–30 | Every employee may preview every summary (a rule that is too broad), so the AI decides. A usual document passes, an unusual one is denied |
| 4 | 31–34 | Narrow rules: the administrator approves and picks the rule, which applies with no second confirmation. A colleague who never asked gets access too |
| 5 | 35–41 | Broad rules: the request waits for the administrator, who declines (only that one document) or reviews the scope and approves |
| 6 | 42–52 | After the decisions: exceptions skip the AI check, rules do not. Repeated, rejected and already readable requests, and an appeal's history |
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

In the log, a small tier is what the app calls a narrow rule, and a large tier a broad one. The log ends with a
summary of all 57 cases, `ok` or `FAIL`, and the command exits with code 1 if a case did not show what it should. On
a stack that was used before, cases fail, so reset it first. The `demo` container reads Envoy's and OPA's logs
through the Docker socket, so it is a tool for your own machine only.

## 2. The document app by hand

Open **http://localhost:8080** on a fresh stack. The sign-in page lists a few accounts to click, and every password
is the demo password ([Settings](getting-started.md#settings)). The username is `e` and the employee number
(`e049`), and the administrator is `admin_01`.

| Account | Who | Used in |
|---|---|---|
| `e040` | Hugo Koch, Engineer, Engineering | 2.1, 2.2, 2.4 |
| `e049` | Chloe Bakker, Coordinator, Engineering | 2.3 |
| `e085` | Oscar Weber, Coordinator, Finance | 2.3, 2.7 |
| `e001` / `e037` | Greta Lim, Manager, Sales / Iris Nugroho, Manager, Engineering | 2.3 |
| `e097` / `e169` | Tono Santoso, Data steward, Finance / Lotte Pratama, Data steward, HR | 2.3 |
| `e110` / `e002` | Eko Smit, Quality lead, Operations / Citra Nugroho, Quality lead, Sales | 2.3 |
| `e111` | Milan Setiawan, Security officer, Operations (EMEA) | 2.4 |
| `e003` | Ana Hartono, Analyst, Sales | 2.5 |
| `admin_01` | Corax administrator: reviews requests | 2.3 to 2.8 |

The current rules let an employee read a document **in one of two ways**. They work on one of its projects, or it is a
*public* document of their own department. Nothing else, whatever their role.

Employees see only what they can open. The rules, their scope and the AI's reasons are for the administrator.

### 2.1 The policy decides

1. Sign in as **`e040`**. **Documents** lists only the documents `e040` may open. The titles of the others are never
   shown. Try the search box, the filters and **My projects**.
2. Open **D033**. The document opens with **Checked by Corax** under its title (`e040` works on one of its projects).
3. Change the id in the address bar to **D130**, a confidential HR document. The page says **No access** and **Denied by Corax**, with
   no title or details. An id that does not exist, such as **D999**, looks exactly the same, so nobody can tell
   which documents exist. That is the BOLA attack the gateway stops.

### 2.2 The AI check

Previews are deliberately too broad. Every employee may preview every document, so the policy allows them all and
the AI risk check decides.

1. Still as **`e040`**, click **Preview** on **D040**. The summary is shown (a usual request for this engineer).
2. Click **Preview** on **D133**. The answer is **Corax blocked this preview**, because it is unlike anything people like `e040`
   read.

### 2.3 Narrow rules: one confirmation

An employee asks for a document of their own department that shares no project with them. The request waits for the
administrator. After the administrator approves, Corax suggests a rule for people in the same situation. One person
per department holds the role, so the rule is **Narrow** (at most 5 people, 50 new accesses and a mean AI risk of
0.5), and it applies as soon as the administrator picks it.

| # | Sign in as | Ask for | The rule the administrator picks | Colleague who never asks: before → after |
|---|---|---|---|---|
| 1 | `e049` Engineering coordinator | **D057** | Coordinators read the documents of their own department | `e085` opens **D070** |
| 2 | `e001` Sales manager | **D011** | Managers read the documents of their own department | `e037` opens **D057** |
| 3 | `e097` Finance data steward | **D074** | Data stewards read the documents of their own department | `e169` opens **D137** |
| 4 | `e110` Operations quality lead | **D101** | Quality leads read the documents of their own department | `e002` opens **D003** |

Scenario 1, step by step:

1. **Before**: sign in as **`e085`**, open **D070** by its link (`#/documents/document_D070`). It shows **No access**. Sign out.
2. Sign in as **`e049`**, open **D057** by its link (a colleague shared it), write a reason ("I coordinate all
   engineering projects") and click **Request access**. The box now says the request, `REQ-DOC-0001`, is waiting for
   an administrator. **My requests** lists it as pending.
3. Sign in as **`admin_01`**. **Requests** opens on **Pending**. Click the document's title to read the request, or
   **Approve** directly. `e049` can read D057 now, and the request page lists Corax's rules for people in the same
   situation, narrowest first, with how many **People** and **Grants** each reaches, its **Risk**, its **Reach** and
   its **Match** with similar requests. Click **Who gains** next to the coordinator rule to see the 4 people and their
   documents, then **Give access**. The rule is **Narrow**, so it applies at once.
4. **After**: sign in as **`e085`** again. **Documents** shows a banner, "new documents were shared with you", and
   **Shared with me** lists **D070** with a **New** badge. It opens, although `e085` never asked. `e049`
   sees only that their request was approved, never the rule.
5. Sign in as **`admin_01`** and open **Access granted**. **Granted** lists the rule and `e049`'s exception, each
   with who approved it, when, how many people and documents it covers, and how often it was used. **Activity**
   has the line "Oscar Weber opened D070" from step 4.

The other three work the same way. `e001`, for example, can then also open D012, D017 and D018, because the rule covers every
Sales document, not only the one asked for.

### 2.4 Broad rules: the administrator decides

When the best rule would open too much (more than 5 people, more than 50 new accesses, or a mean AI risk above 0.5),
it is **Broad**. The administrator sees that before choosing, and has to confirm it a second time.

**Decline, and keep only that one document.**

1. Sign in as **`e040`**, open **D037** (a confidential document of another project) and click **Request access**.
2. Sign in as **`admin_01`**. Under **Pending**, click **Approve**. `e040` gets this one document at once (an exact
   exception), and the request page shows Corax's rules, each in plain words. They are all **Broad**.
3. Click **Only this person**.
4. Sign in as **`e040`**. **D037** opens, but another document of the department, such as **D036**, is still denied.

**Approve a broad rule after reviewing it.**

1. Sign in as **`e111`** (security officer, EMEA), open **D007** and click **Request access**. It waits, because the
   request is unusual and the rule would be broad.
2. As **`admin_01`**, click **Approve**. Before choosing, **Who gains** next to each rule lists the people and documents it
   would open, without writing anything. Then click **Give access** next to rule **#2**, "security officers read what
   is stored in their region".
3. Corax answers **This reaches many people: please confirm**, with the numbers (132 new accesses, mean risk 0.97)
   and the people who would gain access. Click **Confirm and give access**, and the rule is applied.
4. The AI check still applies to every access the rule opens, so unusual ones stay denied.

These requests also wait for the administrator. `e125` (facility manager, Jakarta) asks for **D001**, `e076`
(auditor) for **D029**, `e171` (HR partner) for **D034** and `e147` (HR analyst) for **D001**.

### 2.5 Reject with a note

1. Sign in as **`e003`** (Sales analyst), open **D073** (a Finance document) and click **Request access**. It waits.
2. As **`admin_01`**, click **Reject**, write a note ("Finance documents are for Finance"), then **Reject** again.
3. As **`e003`**, **My requests** shows the rejection and the note, and D073 stays denied.

### 2.6 The administrator's pages

| Page | What it shows |
|---|---|
| **Requests** | Every document and unit request. Tabs **Pending**, **Your decision** (approved, with a rule still to choose), **Decided** and **All**, and a filter for **Documents** or **Units** |
| **Suggested access** | Access Corax expects an employee needs but nobody granted yet ([2.8](#28-access-without-asking)) |
| **Give access** | Every document and every employee, to grant access without a request ([2.8](#28-access-without-asking)) |
| **Access granted** | **Granted**: every rule and exception still in effect. **Activity**: every time that access was used |
| **Audit log** | Every administrator action as Corax recorded it, in a terminal view: who approved what, the rule's pattern, and the three numbers that made it narrow or broad (people reached, new accesses, mean risk) against their limits. Click a line for the raw record |

Administrators do not read documents. Opening one as `admin_01` is denied.

### 2.7 Revoke a rule

As `admin_01`, open the request and use the buttons under **Decision**:

- **Revoke rule** takes the rule back from everyone it reached. The employee who asked keeps their own exception.
- **Revoke all** also takes back the employee's exception.

**Access granted** has a **Revoke** button on every rule and exception too. Each one asks for a confirmation. Corax
then deletes the rule's `.rego` file, records who revoked it and when, and OPA reloads within milliseconds. Access
that the application's own rules grant is not affected.

After scenario 1 of [2.3](#23-narrow-rules-one-confirmation), revoking the rule denies `e085` **D070** again, and D070
disappears from their **Shared with me**. The **Audit log** shows `rule_revoked`.

Deleting the file by hand also revokes the rule, but nothing records it, and **Access granted** flags it as removed
outside Corax:

```bash
docker compose -f deploy/docker-compose.yml exec service rm /runtime/generated/appeal-0001-rule.rego
```

### 2.8 Access without asking

A user cannot ask for what they cannot see. So access can also start from the administrator, and the employee never
learns which documents exist until one is given.

**The administrator gives access.** As `admin_01`, open **Give access**. **Documents** lists every document, and
**Members** shows who can open one already. **Employees** lists every employee, and **Permissions** shows what one can
open already. Click a document's title, pick an employee who cannot open it yet and give a reason. Or click an
employee's name to list only the documents they cannot open. The employee can open it at once, and Corax suggests the
same access for people in the same situation, as for an approved request.

**Corax suggests access.** As `admin_01`, open **Suggested access**. It lists documents Corax expects an employee needs but
nobody gave yet, because most of the 10 people most like them can open it and the request would look normal. Filter
by department or location. **Give access** follows the same steps as above, and **Dismiss** hides a suggestion. The
employee never sees this list.

**An employee asks for a unit.** As an employee, open **My requests** and click **Ask for a unit**. Choose a department
from the list (never typed, never a document title) and say what you need, for example "the grant budget of my
program". As `admin_01`, **Requests** lists it as `REQ-UNIT-0001`. **Decide** shows that department's documents the
employee cannot open yet, ranked by Corax for them, with their **Peer access** and **Risk score**, and a warning when
nobody like them opens anything there. Select the ones to give and click **Grant selected**. Each becomes an approved
request under **Your decision**, and the employee sees how many were shared under **Shared with me**, never the rest
of the unit.

## 3. The Corax console

**http://localhost:8090** shows Corax itself, without the document app. It plays the identity provider, so you pick who
you are, and it signs the token.

1. **Sign in as**: an administrator or an employee, grouped by role.
2. **Read a document**: the request goes through Envoy and OPA. You see allowed or denied, OPA's reason and the AI
   risk.
3. **Approve an appeal** (as the administrator). You see the exact exception, then the candidate rules. Pick one, confirm a
   broad scope, or keep only the exception.
4. **Policy added on top of the application rules** and **Corax activity** show the generated Rego files and every
   appeal's history.

## 4. The before and after table

On a fresh stack:

```bash
docker compose -f deploy/docker-compose.yml run --rm demo scripts/demo_gateway.py run --gateway http://envoy:8080
```

It sends 26 named requests, handles the ten appeals as the administrator directly through Corax's API (each with the
rule it expects), and sends the requests again. It prints a table with each request's AI risk and its answer before
and after the appeals. The appellants and their colleagues go from 403 to 200, the BOLA attempts stay 403, and
accesses that a rule opens but the AI finds unusual stay 403.
