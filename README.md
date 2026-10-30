<h1 align="center">Corax</h1>

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

Corax runs as a sidecar in front of an API. Envoy forwards every request to OPA, which evaluates the
organization's ABAC and ReBAC policy written in Rego. When the policy allows a request, OPA asks the Corax
service for a risk score from a heterogeneous GraphSAGE model of users, objects and their relations, an
implementation of the graph method of [Yin et al. (2024)](docs/references.md).

| Layer | Role | Can it grant access? |
|---|---|---|
| Policy (OPA, Rego) | Final authority, deterministic | Yes |
| AI risk check | Flags requests that passed the policy but do not fit the access graph | No |
| Appeals | Turns an administrator's decision into a rule | Only through a validated rule. Broad rules need a second confirmation |

- **Deny-only AI**: `allow = policy_allow AND NOT ai_high_risk`, written in Rego so it can be audited.
- **Appeals that generalize**: similar cases from a k-nearest-neighbor search on the model's embeddings
  become candidate rules built from the appellant's own facts.
- **Blast-radius tiers**: the share of users reached, the number of new accesses and their mean risk decide
  whether a rule applies at once or waits for a second confirmation.
- **Validated Rego**: syntax, an attribute whitelist, the application's own tests, and equivalence with the
  approved pattern.
- **Live reload, instant revoke**: each rule is its own `.rego` file. OPA loads a new one within milliseconds
  without a restart, and revoking deletes the file.

## Quick start

See the model predict access it has never seen, without Docker:

```bash
python scripts/prepare/make_dummy.py output/dummy-data
python -m hgnn --data output/dummy-data --target-relation accessed --out output/dummy --learning-rate 0.01 --patience 50
python scripts/demo_risk.py --model-dir output/dummy
```

The full demo with Envoy, OPA, the Corax service and a document app, with Docker:

```bash
docker compose -f deploy/docker-compose.yml run --rm prepare
docker compose -f deploy/docker-compose.yml up -d --build
```

Then open http://localhost:8080 for the document app and http://localhost:8090 for the Corax console.

Installation and requirements are in [Getting started](docs/getting-started.md).

## Documentation

<!-- TODO: GitBook link -->
- [Getting started](docs/getting-started.md): requirements, the folders, and deployment
- [Running the demo](docs/demo.md): a guided tour of the document app
- [Architecture](docs/architecture.md): the request path, the service API, the policy and security
- [AI model and evaluation](docs/ai-model-and-evaluation.md): how the model works and how the numbers above were measured
- [Scripts](docs/scripts.md): preparing data, training the model and the demo scripts
- [References](docs/references.md): the research Corax builds on

## License

Released under the [Apache License 2.0](LICENSE). Copyright 2026 The Corax Authors.

## Authors

<!-- TODO -->
- [AgileOrc](https://github.com/AgileOrc)
- [Imkungoingglitch](https://github.com/Imkungoingglitch)
- [waarsss](https://github.com/waarsss)
