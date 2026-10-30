<h1 align="center">Corax: Adaptive Access Control for APIs</h1>

<p align="center">
  <img src="docs/assets/header.png" alt="Corax" width="100%">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue" alt="License: Apache 2.0"></a>
  <img src="https://img.shields.io/badge/Track-Web%20Application%20Security-red" alt="Focus: Web Application Security">
</p>

Most companies control access with fixed rules. An engineer may open engineering files, a manager may open
team reports. Fixed rules have two problems. They let through access that is technically allowed but unusual,
and they block people who genuinely need something the rules did not foresee.

Corax addresses both. It checks every allowed request against how people in similar roles actually work, and
stops the ones that look out of place. When someone is blocked but has a good reason, an administrator can
approve the request, and Corax suggests a rule that would give the same access to colleagues in the same
situation. It shows exactly who that rule would reach before anything changes, and every decision can be
undone later.

## Demo

**The scenario:**</br> A company keeps 160 documents in a shared document application, used by 180 employees across 5 departments. Its fixed rules are simple. People may open the documents of the projects they work on, and the
public documents of their own department. Chloe coordinates every engineering project, but she is not a member
of each one, so the rules keep some engineering documents from her. Oscar coordinates Finance and has the same
problem, although he has not noticed yet.

<!-- TODO: GIFs, cut from the demo video -->

**1. Every request is checked:** Chloe opens an engineering document outside her projects and is blocked. She
sees nothing about it, not even its title, so nobody can find out which documents exist by guessing. Requests the
rules do allow are checked again by Corax, and the ones that do not fit how people like her work are blocked too.

**2. She asks, with a reason:** Chloe writes why she needs the document. The request goes to an administrator,
and she can follow it under "My requests".

**3. One approval, and a suggestion for everyone like her:** The administrator approves, and Chloe can open the
document at once. Corax then suggests rules for people in the same situation, from the narrowest to the
broadest, for example "coordinators may read the documents of their own department". For each one it shows who
would gain access, to which documents, and how unusual that access would be.

**4. The rule reaches the right people:** The administrator picks the coordinator rule. It reaches only a few
people, so it applies at once. Oscar can now open his own department's documents without ever asking. A rule that
would reach many people asks the administrator to confirm it a second time.

**5. Every decision leaves a trace, and can be undone:** The audit log records who approved what, and the numbers
that made the rule narrow or broad. Access granted shows who used the new access and when. If the rule turns out
to be wrong, the administrator revokes it, and the access is gone at once.

Chloe and Oscar are real accounts of the demo, `e049` and `e085`. The full walkthrough is in [Demo Docs](docs/demo.md).

## Why Corax?

Access mistakes are the most common security flaw in web APIs. Broken Object Level Authorization, where a
person reaches data that belongs to someone else, is the first entry of the OWASP API Security Top 10. It
keeps happening because most applications never keep their access rules in one place. Each part of the
system writes its own checks, nobody can review them all, and when the organization changes, the checks
quietly drift apart.

Corax keeps every access rule in one place, enforced in front of every service. On top of those rules, it
adds two things fixed rules cannot do on their own:

- **A second opinion on every allowed request:** A model trained on how people actually use the system flags
  access that is allowed on paper but out of character for that person. It can only block, never grant, so
  its mistakes can never open a door that the rules keep shut.
- **Rules that keep up with the organization:** When an administrator approves an exception, Corax turns
  that decision into a rule for everyone in the same situation, instead of leaving the next person to ask again.

## What Corax does

- **Blocks unusual access** that the fixed rules would have allowed.
- **Turns approvals into rules**, from the narrowest to the broadest, and shows who each rule would reach before it applies.
- **Asks for a second confirmation** when a rule would reach many people or look unusual.
- **Checks every generated rule** against the application's own tests before it takes effect.
- **Takes access back in one click**, and records who did it.
- **Points at access people probably need** but nobody granted yet, for an administrator to review.
- **Keeps a full audit trail** of every approval, rule and revoke, and of every time that access was used.
- **Fits any application** that can describe its people, data and relationships in two CSV files.

## Results

Tested on public data, with every number reproducible from the repository.

| What we measured | Data | Result |
|---|---|---|
| Legitimate requests wrongly blocked | [Amazon Access Samples](https://archive.ics.uci.edu/dataset/216/amazon+access+samples): 36,063 employees, 595,506 accesses | **0.94%**, fewer than 1 in 100 |
| Telling real access from unusual access (AUC, 1.0 is perfect) | Same data | **0.985** against random access, **0.897** against access a colleague has |
| Finding the right rule from a single approval | [Xu & Stoller ABAC policies](https://www3.cs.stonybrook.edu/%7Estoller/software): 45 hidden rules | **Ranked first for 26**, in the top 5 for 37 |
| Same, on rules inferred from Amazon | 10 hidden rules | **In the top 2 for all 10** |

How each number was measured is in [AI model and evaluation](docs/ai-model-and-evaluation.md#evaluation).

## Under the hood
### The building blocks

- **OPA (Open Policy Agent)** is an open-source engine that answers one question for every request, whether it is
  allowed. It is a graduated project of the Cloud Native Computing Foundation and widely used for this job.
- **Rego** is the language OPA rules are written in. A rule reads like "a coordinator may read the documents of
  their own department". Because the rules are code, they can be reviewed, tested and versioned like the rest of
  the software.
- **ABAC and ReBAC** are the two kinds of rules Corax supports. Attribute-based rules look at properties, such as
  a role, a department or a document's classification. Relationship-based rules look at links, such as who works
  on which project or who reports to whom.
- **Envoy** is a widely used proxy, a program that sits between users and an application and passes their
  requests on.

### 2 ways to plug Corax in

Corax can be deployed in 2 ways, and the demo uses both:

- **As a sidecar:** A sidecar is a helper that runs next to an application and takes one job off its hands. Here
  Envoy stands in front of the API and asks OPA about every request before it reaches the application, so the
  application itself needs no access checks.
- **As a policy decision point (PDP):** The PDP is the part that decides, while the application keeps the job of
  enforcing the answer. The application asks OPA "may this person do this?" and acts on the reply. The demo's
  document app does this to list only the documents a user may open.

### How the Corax AI fits in

When the rules allow a request, OPA asks the Corax service for a risk score. The score comes from a graph neural
network, a model that learns from the network of people, documents and how they are connected. Corax uses a
heterogeneous GraphSAGE model, an implementation of the method of [Yin et al. (2024)](docs/references.md).

| Layer | Role | Can it grant access? |
|---|---|---|
| Rules (OPA, written in Rego) | Final authority, the same answer every time | Yes |
| AI risk check | Flags requests that passed the rules but do not fit how people actually work | No |
| Appeals | Turns an administrator's decision into a new rule | Only through a validated rule. Broad rules need a second confirmation |

- **Deny-only AI:** A request is allowed only when the rules allow it and the AI does not find it risky. The AI
  can block a request the rules allow, but it cannot grant access the rules deny. The decision is expressed as a
  single Rego statement, which keeps it open to audit.
- **Appeals that generalize:** The model turns every person and document into a list of numbers, an embedding,
  where similar ones sit close together. Corax looks up the cases closest to the approved one and builds candidate
  rules from the facts of the person who asked.
- **Blast-radius tiers:** The blast radius is how far a rule would reach if it were wrong. Corax measures it by the
  share of people reached, the number of new accesses and how unusual they are, and decides whether a rule applies
  at once or waits for a second confirmation.
- **Validated Rego:** Every generated rule is checked for syntax, uses only allowed attributes, passes the
  application's own tests, and must grant exactly what the administrator approved.
- **Live reload, instant revoke:** Each rule is its own `.rego` file. OPA loads a new one within milliseconds
  without a restart, and revoking deletes the file.

## Quick Start

All you need is Docker. From the repository root:

```bash
docker compose -f deploy/docker-compose.yml run --rm prepare
docker compose -f deploy/docker-compose.yml up -d --build
```

The first command generates the demo company and trains the model, which takes a few minutes the first time. The
second starts the gateway, the policy engine, the Corax service and the document app.

Then open http://localhost:8080 and sign in as Chloe (`e049`) or the administrator (`admin_01`). The sign-in page
lists the demo accounts, and [running the demo](docs/demo.md) walks through every scenario. The requirements and
the full setup are in [Getting Started](docs/getting-started.md).

Without Docker, the same company and model can be explored from Python, without the web app. See
[Demo without Docker](docs/scripts.md#the-demo-company-without-docker).

## Documentation

<!-- TODO: GitBook link -->
The full documentation is also on [GitBook](https://corax.gitbook.io/documentation).

| # | Page | What it covers |
|---|---|---|
| 1 | [Getting started](docs/getting-started.md) | Requirements, the folders, and deployment |
| 2 | [Running the demo](docs/demo.md) | A guided tour of the document app |
| 3 | [Architecture](docs/architecture.md) | The request path, the service API, the policy and security |
| 4 | [AI model and evaluation](docs/ai-model-and-evaluation.md) | How the model works, and how the numbers above were measured |
| 5 | [Scripts](docs/scripts.md) | Preparing data, training the model, and the demo scripts |
| 6 | [References](docs/references.md) | The research Corax builds on |

## License

Released under the [Apache License 2.0](LICENSE).

## Author
- [AgileOrc](https://github.com/AgileOrc)
## Contributor
- [Imkungoingglitch](https://github.com/Imkungoingglitch)
