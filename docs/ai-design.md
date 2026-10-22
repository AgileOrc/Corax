# Corax AI design

This document describes the AI parts of Corax, where they sit in the request path, and the guardrails around them.
The models follow two papers as closely as possible; the parts that are new in Corax are marked as such.

## 1. Principles

1. **Policy code is the source of truth.** Every allow decision comes from Rego evaluated by OPA.
2. **The per-request AI can only deny.** OPA only asks the AI after the policy has already allowed the request.
3. **AI-generated rules can only add allows, never remove denies.**
4. **Every AI-generated rule is validated, logged, and can be revoked** (by deleting its file).

## 2. Architecture

### 2.1 Request path (every request)

```
Client ──► Envoy (PEP) ──► OPA (PDP, opa-envoy-plugin)
                              │  1. verify JWT, parse path
                              │  2. base policy
                              │       deny  ──────────────────────────► 403
                              │       allow ↓
                              │  3. http.send ──► AI-Corax /risk
                              │                     risk = 1 − σ(h_user · h_object)
                              │  4. allow = base_allow AND NOT ai_high_risk
                              ▼
                    allow → Application        deny → 403
```

- Identity comes only from a verified JWT; the object ID comes from the URL path. Both are handled in Rego.
- AI-Corax is only called when the base policy allows the request, so it can never grant access.
- If AI-Corax errors or times out, `ai_high_risk` is false and the policy decision stands. The event is logged.
- If OPA is unreachable, Envoy denies everything (`failure_mode_allow: false`).

The deny-only rule is written explicitly in Rego, so it can be audited:

```rego
allow if {
	base_allow
	not ai_high_risk
}
```

### 2.2 Appeal path (admin approves an exception)

```
Admin ──► Envoy ──► OPA (is the caller an admin?) ──► AI-Corax POST /appeals
                                                          │
  1. Apply an exact exception for the appellant only ─────┤ (immediately)
  2. kNN: similar (user, object) pairs the policy still denies
  3. Pattern miner: shared attributes/relations
  4. Scope: affected users (share of all users), new pairs, mean risk
  5. Tier ── small ─────────────────────────────┐
          └─ large → wait for POST /appeals/{id}/confirm
  6. LLMs write a Rego rule (mixture of agents, majority vote)
  7. Validation (opa check, whitelist, opa test, equivalence with the approved pattern)
  8. Write file to policies/generated/ ──► OPA reloads (--watch)
  Every step is logged.
```

`POST /appeals` returns the mined pattern, its scope and tier, and a status (`applied` or `awaiting_confirmation`).
Policy files are changed only on disk. OPA's REST API is never used for writes and is not exposed.

## 3. Model 1: HGNN

Reimplemented from Yin et al. 2024 (reference code: [ACHG-SSLF](https://github.com/happyResearcher/ACHG-SSLF)).
No code is copied from that repository (it is GPL-3.0); only the method and hyperparameters are reused.

### 3.1 Input format

Corax is not tied to one domain. The HGNN reads two CSV files, described in [data-format.md](data-format.md):
typed nodes and typed edges. One edge type is chosen as the link prediction target.

For the campus demo, the graph maps to the paper like this:

| Paper (Amazon dataset) | Campus demo |
|---|---|
| `user` | `lecturer` |
| `resource` | `student` (the object being accessed) |
| `department` | `program` |
| `title` | `position` (head_of_program, dean, lecturer) |
| `manager` | `reports_to` (lecturer → head_of_program → dean) |
| `has_potential_access` | `accessed` (lecturer → student, from allowed requests only) |

Additional campus edges: `student member_of program`, `program part_of faculty`,
`lecturer teaches course`, `student enrolled_in course`, `course belongs_to program`, `lecturer advises student`.

`position` is a node, not an attribute, so the graph contains the meta-path
`lecturer → position → lecturer` ("both are heads of program"). This is what lets the model see that two heads of program are similar.

### 3.2 Architecture and training

| Item | Value |
|---|---|
| Node input | Learnable `nn.Embedding` per node |
| Encoder | 2 × `SAGEConv` with ReLU, converted with `to_hetero()` |
| Graph | `ToUndirected()` (adds reverse edges) |
| Self-supervised task | Link prediction on the target edge type |
| Decoder | Dot product `h_user · h_object` |
| Loss | Binary cross-entropy with logits |
| Split | `RandomLinkSplit` 0.9 / 0.1, negative sampling ratio 2 |
| Optimizer | Adam, learning rate 0.001 |
| Early stopping | Patience 10 on validation loss |
| Embedding size | 64 to start (paper ablates 16–256) |

**One deliberate difference:** the paper trains in mini-batches with `LinkNeighborLoader`; Corax trains full-batch.
The demo graph is small (about 1,500 nodes), and `LinkNeighborLoader` needs `pyg-lib`, which is hard to install on Windows.
The model and objective are the same.

Output: an embedding per node, saved with the training metadata (and later loaded into AI-Corax).

**Retraining.** Node inputs are learned per node (transductive), so new users or objects only get an embedding
after the job is rerun.

## 4. Use A: risk score (per request)

The risk score reuses the HGNN's own link prediction decoder, so no extra model or labelled data is needed:

```
score = h_user · h_object
p     = σ(score)          how likely this user is to be connected to this object
risk  = 1 − p
```

`ai_high_risk` is true when `risk > AI_RISK_THRESHOLD`.

- The dot product is used (not cosine) because the model was trained with it.
- **Threshold calibration:** the threshold is the risk below which a target share of the legitimate pairs in the
  validation data falls (`target_pass_rate`, default 0.99, i.e. about 1% false deny). The value is an operating
  choice, not taken from Yin et al.: `scripts/evaluate/evaluate_hgnn.py` prints false deny and detection on the test edges
  for 95%, 98%, 99%, 99.5% and 99.9%, and the target is picked from that table. The chosen threshold is stored
  in `metadata.json` (`risk_threshold`). Scores are deterministic, so a legitimate pair that is denied is denied
  every time and can be resolved once through an appeal.
- A lecturer who just started teaching a course has no access history yet, but is still connected to the students through `teaches` / `enrolled_in`, so the score stays reasonable.
- If a user or object has no embedding yet, no score is returned and the policy decision stands.

**Known limit.** The score is about *pairs*, not behaviour over time. It does not detect fast enumeration by an
otherwise legitimate user.

## 5. Use B: similar-case search (Corax contribution)

Not part of either paper. Runs inside `POST /appeals`, e.g. for `(lecturer_budi, student_candra, read_grades, IF202)`.

1. **Candidates:** all (user, object) pairs that the current policy denies for the same action.
2. **kNN:** cosine nearest neighbours of `[h_user ‖ h_object]` among the candidates
   (scikit-learn `NearestNeighbors`).
3. **Pattern miner (deterministic):** evaluate predicates from a fixed vocabulary derived from the schema
   on the appealed pair, its neighbours, and a random baseline of pairs.

| Predicate | Appealed pair | Neighbours | Random pairs |
|---|---|---|---|
| `user.position == "head_of_program"` | ✓ | 95% | 4% |
| `user.program == resource.program` | ✓ | 98% | 30% |
| `user.faculty == resource.faculty` | ✓ | 100% | 55% |
| `teaches(user, resource)` | ✗ | 10% | 8% |

   Pick the smallest conjunction that holds for the appealed pair and most neighbours,
   and rarely holds for random pairs. Here: `position == head_of_program AND same program`.

The miner makes the "why" auditable, and the admin approves a readable pattern, not code.

## 6. Model 2: LLM rule writer

Follows Mai et al. 2025, adapted from Python policies to Rego. Models run locally with Ollama.
The LLM only runs after the tier check has passed (or the admin confirmed), which saves time on slow local models.

| Paper | Corax |
|---|---|
| Knowledge base + RAG, multi-turn prompt with persona and few-shot examples | Prompt contains attribute schema, current policy, appeal, approved pattern, example rules |
| LLM writes a Python policy function with a docstring | LLM writes a Rego rule with a `# METADATA` block (same fields) |
| Mixture of agents: several LLM generators | 2–3 local models run one after another (e.g. `qwen2.5-coder:7b`, `llama3.1:8b`) |
| Deterministic aggregator, majority vote | Same |
| Policy equivalence: AST similarity + identical decisions on a request list | AST from `opa parse` + identical decisions on candidate pairs |
| Deterministic validation (Bandit) | `opa check --strict` + AST check that only whitelisted attributes are used |
| Non-deterministic validation (LLM review) | Same |
| Priority optimization (optional) | Skipped: generated rules are allow-only, so there are no priority conflicts |

Example output:

```rego
# METADATA
# title: head_of_program_read_grades_own_program
# description: A head of program may read grades of students in their own study program.
# custom:
#   appeal_id: appeal-0001
#   attributes: [user.position, user.program, resource.program]
#   votes: 3/3
generated_allow if {
	input.action == "read_grades"
	data.users[input.user.id].position == "head_of_program"
	data.users[input.user.id].program == data.users[input.resource.id].program
}
```

## 7. Validation and tiers

### 7.1 Validation chain (any failure rejects the rule)

1. Rego parses; `opa check --strict` passes.
2. AST uses only whitelisted attributes and only defines `generated_allow`.
3. `opa test` passes, including all existing tests.
4. **Equivalence:** the rule gives exactly the same decisions as the approved pattern on all candidate pairs.
5. The appealed request is now allowed.

### 7.2 Tiers

Computed from the mined pattern, before the LLM runs.

| Input | Source |
|---|---|
| Share of all users who get new access | Exact pairs the pattern opens |
| Number of new (user, object) pairs | Exact pairs the pattern opens |
| Mean risk score of the newly opened pairs | Use A |

| Tier | Condition (configurable) | Action |
|---|---|---|
| Small | user share ≤ `AUTO_APPLY_MAX_USER_SHARE` (0.4) and pairs ≤ `AUTO_APPLY_MAX_PAIRS` (50) and mean risk ≤ `AUTO_APPLY_MAX_MEAN_RISK` (0.5) | Applied automatically, logged |
| Large | anything else | Waits for admin confirmation |

The first design also used the depth of the pattern in a category tree (closer to the root means
more people). It was dropped: Amazon and the Xu & Stoller policies have no such tree, and the user
share already measures how many people are affected. Kept as future work.

Revoking a rule means deleting its file from `policies/generated/`; OPA reloads with `--watch`.

## 8. Safety invariants

1. `allow = base_allow AND NOT ai_high_risk`; the AI risk score can only turn allow into deny.
2. Generated rules only add `generated_allow` clauses and live only under `policies/generated/`.
3. Every generated rule records its origin: appeal id, neighbours, pattern, votes, scope.
4. Access granted by a generated rule still goes through the risk score.
5. Policies change only through files; OPA's REST API is not used for writes and is not exposed.

## 9. Threats and mitigations

| Threat | Mitigation |
|---|---|
| A socially engineered appeal gets generalised | Appeals are approved by a human admin; tiers and scope limit the blast radius |
| Graph poisoning (Zhang et al. 2022) | `accessed` edges come only from allowed requests; risk score checks newly opened pairs |
| Prompt injection into the LLM | LLM input is structured, sanitised data; output must pass the AST whitelist and equivalence check |
| Over-generalisation | Smallest conjunction, scope count, depth tiers |
| AI-generated rule is wrong | Equivalence check; risk score still denies suspicious pairs (demo 2) |
| Non-admin calls `/corax/appeals` | OPA allows `corax.*` actions only for `config.admin.users`; application rules and generated rules cannot grant them |
| Someone reaches AI-Corax directly, bypassing Envoy and OPA | AI-Corax verifies the admin's JWT itself (same key, `iss`, `aud` and admin list as OPA, read from the same `data.json`; algorithm fixed by key type; `exp` and `sub` required) and is only exposed on the internal network |
| Forged identity header (`x-corax-user`) | AI-Corax ignores it; the audit log takes the admin from the verified JWT |
| A generated rule tries to make someone an admin or touch other policy | Generated files may only define `allow` in `app.generated` / `app.exceptions` (AST whitelist), and `corax.*` actions ignore those packages |

## 10. Evaluation

The synthetic data generator hides **ground-truth policies** (e.g. "a head of program may read grades of students in their program"),
so the pipeline can be measured end to end.

| Component | Metric |
|---|---|
| HGNN | Link prediction AUC on validation set |
| Risk score | False deny rate on legitimate requests, detection rate on over-broad-rule requests, p99 latency |
| Similar-case search | Precision@k (neighbours covered by the hidden policy) |
| Whole pipeline | **Rule recovery rate**: share of appeal scenarios that produce a rule equivalent to the hidden policy |

## 11. Demo scenarios

| Demo | Story | Shows |
|---|---|---|
| 01 | A student swaps the ID in the URL to read a classmate's grades → 403 | Policy stops BOLA |
| 02 | An over-broad rule ("lecturers may read grades in their faculty") lets `lecturer_andi`, a new lecturer with no relations, request `student_dewi`'s grades → policy ALLOW, AI DENY | AI can only tighten, even when a rule is wrong |
| 03 | `lecturer_budi` (head of program IF) is denied, admin approves his appeal → exception applied → HGNN finds `lecturer_sari` (head of program SI) → LLM writes the head-of-program rule → Sari gets access without appealing | Appeals generalise to similar cases |

## 12. Requirements for the data generator

- Category tree, users, objects, and all edges in section 3.1, in the format of [data-format.md](data-format.md).
- `accessed` history from allowed requests only.
- Hidden ground-truth policies for evaluation.
- Legitimate and over-broad-rule requests for threshold calibration and evaluation.
- Appeal scenarios with expected rules, including one that should not generalise.

## 13. Future work

- Rule expiry (auto-applied rules expire unless an admin makes them permanent).
- Behaviour features (request rate) to detect enumeration.
- Inductive node features so new users get embeddings without retraining.
- Mini-batch training for large graphs.

## 14. References

- Yin et al., *A heterogeneous graph-based semi-supervised learning framework for access control decision-making*, World Wide Web 2024. Code: https://github.com/happyResearcher/ACHG-SSLF (GPL-3.0, not copied).
- Mai et al., *LLM-Based Fine-Grained ABAC Policy Generation*, ICISSP 2025.
- Zhang et al., *Robust Heterogeneous Graph Neural Networks against Adversarial Attacks*, AAAI 2022.
