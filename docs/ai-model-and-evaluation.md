# AI model and evaluation

How Corax scores a request, how it turns an approved appeal into candidate rules, and how both were
evaluated.

## Risk score

### Background

The model is Corax's own implementation of the heterogeneous graph method in [[1]](references.md), with the architecture and hyperparameters described there. Users, objects and everything that connects them (departments, roles, projects, managers) are nodes of one typed graph. Past access is one edge type, and the model learns to predict it (link prediction).

### What Corax adds

- **The decoder is the risk score.** No separate classifier is trained on top of the embeddings. The
  dot product the model was trained with gives the risk of user *u* reading object *o*:

  $$
  \mathrm{risk}(u, o) = 1 - \sigma\left(\mathbf{h}_u^{T} \mathbf{h}_o\right),
  \qquad \sigma(x) = \frac{1}{1 + e^{-x}}
  $$

  Applications rarely have labeled examples of access that should be denied, and this needs none.
- **The model only checks, after the policy.** It runs once the policy has already allowed a request
  and can only turn that allow into a deny, so its mistakes can cost a false deny but never a false allow.
- **A calibrated threshold.** Set so that 99% of real access in the validation split passes.
- **Hard negatives** (optional, `--hard-negative-ratio`). Some training negatives are objects a peer of
  the user has, the realistic case of a misconfigured rule. On Amazon they raise the AUC on such pairs
  from 0.675 to 0.897 ([Evaluation](ai-model-and-evaluation.md#evaluation)).
- **A held-out test split** (80%/10%/10%), so reported numbers come from edges never used for training
  or calibration.
- **The same embeddings find similar cases** (kNN) for [appeals](#appeal-path).

### Graph

Corax is not tied to one domain. It reads typed nodes and typed edges from two CSV files
([data format](scripts.md#data-format)). One edge type is the target. For the example used in these
docs, a company whose employees read reports:

| Amazon dataset | Example company |
|---|---|
| `user` | `employee` (e.g. `alice`) |
| `resource` | `report` (the object being accessed, e.g. `report_105`) |
| `department` | `department` |
| `title` | `role` (`role_manager`, `role_staff`) |
| `has_potential_access` | `accessed` (employee → report, from allowed requests only) |

A role is a node, not an attribute, so the graph contains the path `employee → role → employee`
("both are managers"). This is what lets the model see that two managers are similar.

### Model and training

| Item | Value |
|---|---|
| Node input | Learnable `nn.Embedding` per node |
| Encoder | 2 × `SAGEConv` with ReLU, converted with `to_hetero()`. `ToUndirected()` adds reverse edges |
| Decoder | Dot product `h_user · h_object` |
| Loss | Binary cross-entropy with logits, 2 negatives per positive |
| Split | `RandomLinkSplit` 80 / 10 / 10: train, validation (early stopping, threshold), test (evaluation only) |
| Optimizer | Adam, learning rate 0.001, patience 10, embedding size 64 |
| Hard negatives | Optional share of negatives taken from a peer's objects (`--hard-negative-ratio`, 0.5 on Amazon) |

Training is full-batch, because the graphs fit in memory and `LinkNeighborLoader` needs `pyg-lib`, which is hard
to install on Windows.

Node inputs are learned per node (transductive). A new user or object only gets an embedding after
retraining. Until then `/risk` returns no score and the policy decision stands.

### From embeddings to risk

```
p     = σ(h_user · h_object)     how likely this user is to be connected to this object
risk  = 1 − p
deny  when risk > threshold
```

The dot product is used, not cosine, because the model was trained with it.

**Threshold.** The risk below which 99% of the real access in the validation split falls
(`--target-pass-rate 0.99`, about 1% false deny). It is an operating choice.
`scripts/evaluate/evaluate_hgnn.py` prints false deny and detection on the test split for 95%, 98%,
99%, 99.5% and 99.9%. The value is stored in `metadata.json` and can be overridden with
`AI_RISK_THRESHOLD`. Scores are deterministic, so a legitimate pair that is denied is denied every
time and can be resolved once through an appeal.

An employee who just joined a project has no access history yet, but is connected to the project's
reports through `works_on` and `belongs_to`, so the score stays reasonable.

## Appeal path

A user is denied, an admin decides they should have access. The appellant gets an exact exception at
once, then Corax looks for other people in the same situation and proposes a rule for all of them. Every step is deterministic and can be replayed.

![Appeal path](assets/architecture-appeal.png)

**Phase 1: the admin files the appeal**, `POST /corax/appeals`.

1. The exact exception for the appellant is written at once.
2. kNN finds the most similar pairs that have no access yet.
3. Candidate rules are built from the appellant's own facts and returned, narrowest first, each with a
   plain-language sentence and the users and pairs it would open. The admin can preview the full list of
   who would gain access to what (`GET /corax/appeals/{id}/candidates/{n}`).

**Phase 2: the admin accepts one of the proposed rules**, `POST /corax/appeals/{id}/confirm`.

4. Corax computes the scope of the chosen rule, which is its share of users, new pairs and mean risk.
5. A small rule continues. A large one returns 409, with the users who would gain access, until the
   admin confirms again with `acknowledge_scope`. The admin can also keep only the exception.
6. The rule is written as Rego from a fixed template and validated (syntax, whitelist, the application's
   tests, equivalence with the pattern). A rule that fails is not written.
7. The file is written atomically to `policies/generated/`. OPA, which watches the folder, loads it within
   milliseconds.
8. A snapshot of who gained access to what is written next to the appeal record.

**Afterwards: every use is logged.** The users in the snapshot reach their new resources without another
approval. Each time they do, the service logs it. OPA's `/risk` call shows the pair, and for the appellant's
exception, which skips `/risk`, OPA calls `/usage`. `GET /corax/rules` shows every rule in effect, who
gained access and how it was used, in plain language. `GET /corax/me/access` shows a user the resources
they can reach through appeals.

**Phase 3 (optional): revoke**, `POST /corax/appeals/{id}/revoke`. The rule's file is deleted, OPA
reloads the same way, and who revoked it and when is recorded. Deleting the file by hand also works but
is not recorded.

**Without an appeal.** A user cannot ask for what they cannot see, and an application should not show
titles of objects someone may not open (`corax/authz/allowed_objects` lists only the allowed ones). So
access can also start from the admin, through the same flow:

- **The admin gives access** to someone who joined a team or changed role, with `POST /corax/appeals` and the
  admin's token, without any request.
- **Corax suggests access** the model expects but nobody granted (`GET /corax/suggestions`), when most of the
  user's closest peers can reach the object, and the risk is low.
- **A user asks for a whole unit** (e.g. a department, chosen from a list, never typed) without naming a
  document. Corax ranks that unit's objects for them (`POST /corax/rank`) and the admin picks.

Policy files change only on disk. OPA's REST API is never used for writes and is not exposed.

| Written | Where | When |
|---|---|---|
| `<id>-exception.rego` (package `app.exceptions`) | `policies/generated/` | Phase 1 |
| `<id>-rule.rego` (package `app.generated`) | `policies/generated/` | Phase 2, if the admin accepts a rule |
| Appeal record with its history (audit log) | `appeals/` | Every step |
| `<id>-granted.json`: who gained access to what | `appeals/` | Phase 1 (exception) and phase 2 (rule) |
| `<id>-usage.jsonl`: every use of that access | `appeals/` | Each allowed request it covers |

The steps in detail use an illustrative example. `alice`, the manager of the sales department, is
denied `report_105`, a report of that department, because no rule covers managers yet.

### 1. Exact exception

`<id>-exception.rego` in package `app.exceptions`, written as soon as the appeal is created:

```rego
allow if {
	input.user.id == "alice"
	input.resource.id == "report_105"
	input.action == "read_report"
}
```

The admin reviewed this exact pair, so it skips the AI risk check.

### 2. Similar cases (kNN)

The most similar (user, object) pairs that have no access yet. Similarity of a pair is the mean of the
cosine similarity of the users' embeddings and of the objects' embeddings. At most 2 pairs per user
(`max_per_user`), so one user cannot fill the list. The cases are evidence for the admin. They do not
decide the rule.

### 3. Candidate patterns

Candidates are built only from the appellant's own facts in the graph, as conjunctions of up to two
predicates:

| Kind | Reads as | Example |
|---|---|---|
| `user_has` | user has a value | `user holds role_manager` |
| `object_has` | object has a value | `object type invoice` |
| `shared` | user and object share a node | `user.member_of = object.member_of` |
| `direct` | user is linked to the object | `user owns object` |
| `object_is` | one specific object (systems in Amazon, off by default) | `object is resource_42` |

**Too specific values are skipped**, such as a value both the user and the object have (the `shared` candidate
covers it for every value) and a value of an attribute with several values (one of the projects a
user works on). Otherwise one slice per value would rank above the general rule, because it opens fewer
pairs.

Candidates are ordered **narrowest first**, by fewest new pairs, then fewest users, then fewest
predicates, then highest kNN support. For each one the admin sees how many users and pairs it opens
and what share of the similar cases it covers:

```
  #  users      pairs   kNN  pattern
  1      3         12   20%  user.member_of = object.member_of AND user works_on project_sales_1
  2      6         45   10%  user.member_of = object.member_of AND user holds role_manager
  4     28        105   30%  user.member_of = object.member_of
```

Each candidate also comes as a plain-language sentence for the admin, built from the same predicates as the
Rego file. With the application's optional `labels`, #2 reads:

```
An employee may read a report when the employee and the report have the same department and the employee is a manager.
```

The admin accepts one (here #2) or none (`exception_only`).

### 4. Tier

Computed from the exact pairs the chosen pattern opens:

| Input | Limit (environment variable, default) |
|---|---|
| Share of all users who get new access | `AUTO_APPLY_MAX_USER_SHARE`, 0.4 |
| New (user, object) pairs | `AUTO_APPLY_MAX_PAIRS`, 50 |
| Mean risk of the new pairs | `AUTO_APPLY_MAX_MEAN_RISK`, 0.5 |

A **small** rule (all within limits) is applied and logged. For a **large** one (any limit exceeded), the confirm call returns
409 with the scope until the admin repeats it with `acknowledge_scope: true`.

No regulation fixes these numbers. ISO 27001, NIST 800-53, PCI DSS and SOC 2 require that access grants
are approved and logged, not a size limit, so they are set to the organization's risk appetite.
`AUTO_APPLY_MAX_USER_SHARE=0` makes every rule wait for an admin.

### 5. Rego

Written from a fixed template into package `app.generated`, with the pattern, scope and tier recorded
as metadata:

```rego
# METADATA
# title: "appeal-0001"
# description: "user.member_of = object.member_of AND user holds role_manager"
# custom:
#   appeal_id: "appeal-0001"
#   users: 6
#   pairs: 45
#   tier: "small"
allow if {
	input.action == "read_report"
	some n1 in data.corax.graph[input.user.id]["member_of"]
	n1 in data.corax.graph[input.resource.id]["member_of"]
	"role_manager" in data.corax.graph[input.user.id]["holds"]
}
```

`data.corax.graph` is `graph.json`, written by `python -m hgnn` and loaded by OPA.

### 6. Validation

Any failure rejects the rule (422) and nothing is written:

1. **Syntax**: `opa check --strict`.
2. **Whitelist**: the AST may only define `allow` in `app.generated` or `app.exceptions`, read only
   `input.action`, `input.user.id`, `input.resource.id` and `data.corax.graph`, and use only equality
   and membership.
3. **Application tests**: `opa test` on the application's policy folder still passes (`POLICY_DIR`).
4. **Equivalence**: OPA gives exactly the decisions of the pattern on the appealed pair, the pairs it
   opens and 500 random pairs.

The file is then written atomically, so OPA never loads half a file. Revoking a rule means deleting
its file, through `POST /corax/appeals/{id}/revoke` so that it is recorded.

## Evaluation

Every number below comes from a model trained once with `python -m hgnn` and scored by a script that
only loads it (`scripts/evaluate/`). The commands are in [Scripts](scripts.md#scripts).

### Risk score: Amazon Access Samples

UCI Amazon Access Samples (CC BY 4.0) has 36,063 users, 33,252 resources, 405 departments, 4,979 titles,
3,207 managers, 595,506 access edges. Split 80 / 10 / 10, the test edges are never used in training.

- **Random negatives**: random (user, resource) pairs without access.
- **Hard negatives**: a resource a peer of the user (same department, title or manager) has, but the
  user does not. They look normal, which makes them the realistic case for a misconfigured rule.

| Model | AUC random | AUC hard | Threshold | False deny | Detection random | Detection hard |
|---|---|---|---|---|---|---|
| Base | 0.995 | 0.675 | 0.988 | 0.85% | 90.5% | 6.4% |
| 50% hard negatives in training (chosen) | 0.985 | 0.897 | 0.978 | 0.94% | 78.8% | 24.5% |

The threshold is calibrated so that 99% of real access in the validation split passes. Training with
hard negatives costs some detection of random pairs but almost quadruples detection of hard ones, at
the same false deny rate.

### Appeals: hidden rules

The benchmarks are the university ABAC policies of [[6]](references.md) and rules inferred from the Amazon data.
A rule is removed from the data, the model is trained without it, and one of its pairs is appealed. A
good appeal flow puts that rule near the top of the candidate list.

- **P@10**: share of the 10 similar cases that belong to the hidden rule.
- **Rank**: position of the hidden rule among the candidates.
- **Tier**: of the hidden rule, under the default limits (40% of users, 50 pairs, mean risk 0.5).

| Data | Appeals | P@10 | Rank 1 | Top 5 | Tier of the rule |
|---|---|---|---|---|---|
| Xu & Stoller university policies (5 files × 9 rules) | 45 | 34% | 26 | 37 | 45 large |
| Amazon, inferred "title T gets resource R" rules | 10 | 70% | 1 | 10 | 8 small, 2 large |
| Dummy data, "head of program reads own students" | 1 | 10% | 0 | 1 | small |

Appeals that should not generalize (a lecturer asking for a student of another program, a one-off
Amazon grant) produce only large candidates on every dataset, so they wait for an admin.

The Xu & Stoller rules are all large because each grants more than 50 pairs, and rules 1, 6 and 9 reach
60 to 75% of the users. That is the intended behavior, because a rule that broad needs a human.

**Known weakness.** Rules that slice by an attribute of the object only (Xu & Stoller rules 4 and 8)
rank lower (5 to 11), because every value of that attribute gives a narrower candidate.

### Reproduce

- Xu & Stoller: [Scripts → Xu & Stoller](scripts.md#xu--stoller-abac-policies). The `.abac`
  files are GPL-3.0 and are not part of this repository.
- Amazon: [Scripts → Amazon](scripts.md#amazon-dataset).
- Dummy data: [Getting started](getting-started.md).
