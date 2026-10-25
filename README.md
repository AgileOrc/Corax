<h1 align="center">Corax: Authorization Policies That Learn from Admin Decisions</h1>

<p align="center">
  <img src="docs/assets/header.png" alt="Corax" width="100%">
</p>

<p align="center">
  <b>Policy-as-code authorization against BOLA, with an AI that can only deny.</b><br>
  Rego (policy code) decides every request. A graph neural network flags the ones that don't fit, and turns an admin's approved exception into a validated rule for everyone in the same situation.
</p>

<p align="center">
  <!-- TODO: badges, e.g. CI, license -->
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-TODO-blue"></a>
</p>

| Case | What happens | Result |
|---|---|---|
| 1 | A user requests a resource the policy does not allow | **403**: denied by policy |
| 2, 3 | An over-broad rule lets requests through policy | The pair that fits the access graph gets **200**, the odd one gets **403**, the **Corax AI denies** it |
| 4 | An admin approves one user's appeal and the rule is small | Rule generated, validated and loaded by OPA (policy engine) **without restart**. A different user in the same situation, who never appealed, gets **200** |
| 5 | An appeal whose rule would be large | **409**: waits for the admin, who declines and keeps only the exact exception |
| 6 | Another large appeal | The admin approves after reviewing its scope and the rule is applied |
| 7 | The rule file is deleted | **403** again: a rule is rolled back by deleting its file |

The demo runs on dummy data, the full walkthrough is in [getting started](docs/getting-started.md#3-end-to-end-demo-with-docker).

## Why Corax?

Broken Object Level Authorization (OWASP API1) keeps happening because most applications never define their authorization rules in one place. Each service writes its own checks, ad hoc and inline, so there is no single set of rules to review, test or audit. When the organization changes, a new role or a new kind of access, every service has to be updated separately, and the checks quietly drift apart. A system built like this is hard to keep resilient.

Pure machine-learning access control is no answer either: models are hard to audit, hard to update when the rules change, and can be deceived.

Corax keeps all authorization rules as one policy code, the single source of truth, enforced in front of every service. When the organization needs a new rule, an admin's approved exception becomes a validated rule in that policy code, so it keeps up with how access is really granted instead of falling behind.

AI sits only where its mistakes cannot become a false allow. The risk check runs after the policy has already allowed a request and can only turn that allow into a deny. In appeals, AI only suggests similar cases, an admin accepts the rule, and every rule is validated before it takes effect.

| Layer | Role | Can it grant access? |
|---|---|---|
| Policy (OPA / Rego) | Final authority, deterministic | Yes |
| AI risk check | Flags requests that passed policy but don't fit the access graph | No|
| Appeals | Generalizes an admin's decision into a rule | Only through a validated rule. Broad rules need a second confirmation |

## Capabilities

- **Deny-only AI**: `allow = policy_allow AND NOT ai_high_risk`, written in Rego so it can be audited
- **Graph risk score** from a heterogeneous GraphSAGE model of users, objects and their relations
- **Appeals that generalize**: similar cases (kNN on embeddings) --> candidate rules from the appellant's own facts, narrowest first
- **Blast-radius tiers**: share of users, new pairs and mean risk decide whether a rule applies at once or waits for an admin
- **Validated Rego**: syntax, attribute whitelist, the application's own tests, and equivalence with the approved pattern
- **Live reload, instant revoke**: each rule from an appeal is saved as its own `.rego` file, OPA watches that folder and loads a new rule within milliseconds, without a restart. Deleting the file revokes the rule
- **Domain-agnostic**: any application described as typed nodes and edges in two CSV files

## Results

| | Data | Result |
|---|---|---|
| Risk score | [Amazon Access Samples](https://archive.ics.uci.edu/dataset/216/amazon+access+samples) (36k users, 595k access edges) | AUC 0.985 random / 0.897 hard negatives, 0.94% false deny |
| Appeals | [Xu & Stoller ABAC policies](https://www3.cs.stonybrook.edu/%7Estoller/software) (45 hidden rules) | Hidden rule ranked first for 26/45, top 5 for 37/45 |
| Appeals | Amazon, inferred role rules (10 hidden rules) | Hidden rule in the top 2 for 10/10 |

Details: [Evaluation](docs/evaluation.md).

## Quick start

See the model predict access it has never seen, without Docker:

```bash
python scripts/prepare/make_dummy.py output/dummy-data
python -m hgnn --data output/dummy-data --target-relation accessed --out output/dummy --learning-rate 0.01 --patience 50
python scripts/demo_risk.py --model-dir output/dummy
```

End-to-end demo with Envoy, OPA and the service (Docker):

```bash
docker compose -f deploy/docker-compose.yml up --build -d
bash deploy/demo/demo.sh
```

Installation and walkthrough: [Getting started](docs/getting-started.md)

## Documentation

<!-- TODO: GitBook link -->
Full documentation: **[GitBook](https://TODO)** (also in [`docs/`](docs/README.md)).

## License

<!-- TODO -->
Released under the [TODO](LICENSE) license.

## Authors

<!-- TODO -->
- [Vienenta Graciella](https://github.com/AgileOrc)
- [Fredly Artha Immanuel](https://github.com/Imkungoingglitch)
- [Daniel Agatha](https://github.com/waarsss)

## Prior Research
[1] J. Yin, G. Chen, W. Hong, J. Cao, H. Wang, and Y. Miao, "A heterogeneous graph-based semi-supervised learning framework for access control decision-making," *World Wide Web*, vol. 27, no. 4, Art. no. 35, 2024, doi: [10.1007/s11280-024-01275-2](https://doi.org/10.1007/s11280-024-01275-2).