# Corax AI design

This document describes the two AI models in Corax, how they are used, and the guardrails around them.
The models follow two papers as closely as possible; the parts that are new in Corax are marked as such.

## 1. Principles

1. **Policy code is the source of truth.** Every allow decision comes from Rego evaluated by OPA.
2. **The per-request AI can only deny.** It never turns a policy deny into an allow.
3. **AI-generated rules can only add allows, never remove denies.** Explicit deny guards always win.
4. **Every AI-generated rule expires, is logged, and can be revoked.**

## 2. Overview

```
                 ┌──────────── MODEL 1: HGNN (offline job) ────────────┐
Campus graph ──► │ heterogeneous GraphSAGE → one embedding per node     │──► Redis
                 └──────────────────────────────────────────────────────┘
                           │                              │
              Use A        ▼                              ▼        Use B
     Risk classifier (every request)          Similar-case search (on admin appeal)
     Random Forest, deny-only                 kNN → pattern miner (deterministic)
                                                          │
                                                          ▼
                                       MODEL 2: local LLMs (Ollama)
                                       pattern → Rego rule (mixture of agents)
                                                          │
                                                          ▼
                              validation → impact test → decision engine
                              (depth, affected users, sensitivity, risk score)
                                                          │
                                                          ▼
                              policies/generated/*.rego (with expiry)
```

One HGNN is trained once and its embeddings are used twice:

| | Use A: risk check | Use B: similar cases |
|---|---|---|
| When | Every request that OPA allowed | When an admin approves an appeal |
| How | Random Forest on pair embeddings → risk score | Nearest neighbours of the approved pair |
| Output | risk > threshold → 403 | Shared attributes/relations → LLM |

## 3. Model 1: HGNN

Reimplemented from Yin et al. 2024 (reference code: [ACHG-SSLF](https://github.com/happyResearcher/ACHG-SSLF)).
No code is copied from that repository (it is GPL-3.0); only the method and hyperparameters are reused.

### 3.1 Graph schema (access control heterogeneous graph)

| Paper (Amazon dataset) | Corax (campus) |
|---|---|
| `user` | `dosen` |
| `resource` | `mahasiswa` (the object being accessed) |
| `department` | `prodi` |
| `title` | `jabatan` (kaprodi, dekan, dosen) |
| `manager` | `atasan` (dosen → kaprodi → dekan) |
| `has_potential_access` | `pernah_akses` (dosen → mahasiswa, from allowed requests only) |

Additional campus edges: `mahasiswa anggota prodi`, `prodi bagian_dari fakultas`,
`dosen mengajar matkul`, `mahasiswa mengambil matkul`, `matkul milik prodi`, `dosen wali_dari mahasiswa`.

`jabatan` is a node, not an attribute, so the graph contains the meta-path
`dosen → jabatan → dosen` ("both are kaprodi"). This is what lets the model see that two kaprodi are similar.

### 3.2 Architecture and training

Same as the paper:

| Item | Value |
|---|---|
| Node input | Learnable `nn.Embedding` per node |
| Encoder | 2 × `SAGEConv` with ReLU, converted with `to_hetero()` |
| Graph | `ToUndirected()` (adds reverse edges) |
| Self-supervised task | Link prediction on `pernah_akses` |
| Decoder | Dot product `h_dosen · h_mahasiswa` |
| Loss | Binary cross-entropy with logits |
| Split | `RandomLinkSplit` 0.9 / 0.1, negative sampling ratio 2 |
| Optimizer | Adam, learning rate 0.001 |
| Early stopping | Patience 10 on validation loss |
| Embedding size | 64 to start (paper ablates 16–256) |

Output: embeddings for every node, written to Redis (`emb:<version>:<node_type>:<id>`).

**Retraining.** Because node inputs are learned per node (transductive), new users or students only get an
embedding after the job is rerun. `hgnn-job` therefore runs periodically and after data changes.

## 4. Use A: risk classifier

| Item | Value |
|---|---|
| Features | NodeEmb+: `[h_dosen ‖ h_mahasiswa]` + original attributes |
| Model | Random Forest, `n_estimators=100`, `max_depth=50`, `random_state=0` (as in the paper) |
| Training data | Only policy-allowed requests, labelled normal / suspicious |
| Metric | F1 of the minority (suspicious) class, p99 latency < 20 ms |

Decision in `authz-service`:

```
final_allow = policy_allow AND NOT (risk > AI_RISK_THRESHOLD)
```

- The classifier is only called when `policy_allow` is true, so it can never grant access.
- On model error or timeout (`AI_TIMEOUT_MS`), the policy decision stands and the event is logged.

**Why deny-only.** The paper's best configuration (RF + NodeEmb+) reaches about 76% accuracy.
That is useful as a risk signal, but not good enough to grant access.

**Known limit.** The model scores *pairs*, not behaviour over time. It does not detect fast enumeration
by an otherwise legitimate user. This is a deliberate choice to stay faithful to the paper.

## 5. Use B: similar-case search (Corax contribution)

Not part of either paper. Triggered when an admin approves an appeal, e.g.
`(dosen_budi, mhs_x, read_nilai, IF201)`.

1. **Candidates:** all (dosen, mahasiswa) pairs that the current policy denies for the same action.
   These are the only pairs a new allow rule could change.
2. **kNN:** cosine nearest neighbours of `[h_budi ‖ h_x]` among the candidates
   (scikit-learn `NearestNeighbors`).
3. **Pattern miner (deterministic):** evaluate predicates from a fixed vocabulary derived from the schema
   on the approved pair, its neighbours, and a random baseline of pairs.

| Predicate | Approved pair | Neighbours | Random pairs |
|---|---|---|---|
| `user.jabatan == "kaprodi"` | ✓ | 95% | 4% |
| `user.prodi == resource.prodi` | ✓ | 98% | 30% |
| `user.fakultas == resource.fakultas` | ✓ | 100% | 55% |
| `mengajar(user, resource)` | ✗ | 10% | 8% |

   Pick the smallest conjunction that holds for the approved pair and most neighbours,
   and rarely holds for random pairs. Here: `jabatan == kaprodi AND same prodi`.

The miner makes the "why" auditable. The LLM only receives predicates that exist in the schema.

## 6. Model 2: LLM rule writer

Follows Mai et al. 2025, adapted from Python policies to Rego. Models run locally with Ollama.

| Paper | Corax |
|---|---|
| Knowledge base + RAG, multi-turn prompt with persona and few-shot examples | Prompt contains attribute schema, current policy, approved appeal, mined pattern, neighbour summary, example rules |
| LLM writes a Python policy function with a docstring | LLM writes a Rego rule with a `# METADATA` block (same fields) |
| Mixture of agents: several LLM generators | 2–3 local models run one after another (e.g. `qwen2.5-coder:7b`, `llama3.1:8b`) |
| Deterministic aggregator, majority vote | Same |
| Policy equivalence: AST similarity + identical decisions on a request list | AST from `opa parse` + identical decisions on synthetic requests |
| Deterministic validation (Bandit) | `opa check --strict` + AST check that only whitelisted attributes are used |
| Non-deterministic validation (LLM review) | Same |
| Priority optimization (optional) | Skipped: generated rules are allow-only and deny guards always win, so there are no priority conflicts |

Example output:

```rego
# METADATA
# title: kaprodi_read_nilai_own_prodi
# description: A kaprodi may read grades of students in their own study program.
# custom:
#   appeal_id: appeal-0001
#   attributes: [user.jabatan, user.prodi, resource.prodi]
#   votes: 3/3
#   expires_ns: 1792800000000000000
generated_allow if {
	input.action == "read_nilai"
	data.users[input.user.id].jabatan == "kaprodi"
	data.users[input.user.id].prodi == data.mahasiswa[input.resource.id].prodi
	time.now_ns() < 1792800000000000000
}
```

The expiry is checked inside Rego, so the rule stops working on time even if the cleanup job fails.

## 7. Validation and decision engine

### 7.1 Validation chain (any failure rejects the rule)

1. Rego parses; `opa check --strict` passes.
2. AST uses only whitelisted attributes and only writes `generated_allow`.
3. `opa test` passes, including all existing tests and deny guards.
4. The approved appeal is now allowed (sanity check).
5. Impact test: replay historical requests on old and new policy, e.g.
   "changes 340 decisions for 6 users".

### 7.2 Decision inputs

| Input | Source |
|---|---|
| Depth of the lowest common category covered by the rule | Category tree |
| Number of affected users and changed decisions | Impact test |
| Action sensitivity (`data-pribadi` > `nilai`) | Config |
| LLM vote agreement (e.g. 3/3 vs 2/3) | Model 2 |
| Mean risk score of the newly allowed pairs | Use A |

The last row means **Use A audits Use B**: if the pairs a new rule would open look risky to the classifier,
the rule is not applied automatically.

### 7.3 Tiers

Example category tree: `root (0) → dosen (1) → fakultas (2) → prodi (3) → jabatan (4)`.
Closer to the root means more people are affected.

| Depth | Example scope | Action | Expiry |
|---|---|---|---|
| ≥ 3 | One prodi, few users | Applied automatically | 7 days |
| 2 | One fakultas | Applied automatically, admin notified | 24 hours |
| ≤ 1 | All lecturers or cross-faculty | Waits for admin approval | — |

Sensitive actions (`data-pribadi`) get half the expiry. All values are configurable.
Expired rules are removed unless an admin promotes them to permanent.
Revoking a rule means deleting its file from `policies/generated/`; OPA reloads with `--watch`.

## 8. Safety invariants

1. Final decision: `allow = (base_allow OR generated_allow) AND NOT explicit_deny`.
   Deny guards live in a separate file that the AI cannot write.
2. AI only writes files under `policies/generated/`.
3. Every generated rule records its origin: appeal id, neighbours, votes, impact test result.
4. Access granted by a generated rule still goes through the risk classifier.
5. Expiry is enforced inside Rego.

## 9. Threats and mitigations

| Threat | Mitigation |
|---|---|
| A socially engineered appeal gets generalised | Appeals are approved by a human; tiers, impact test and expiry limit the blast radius |
| Graph poisoning (Zhang et al. 2022) | `pernah_akses` edges come only from allowed requests; risk classifier checks newly opened pairs |
| Prompt injection into the LLM | LLM input is structured, sanitised data; output must pass the AST whitelist |
| Over-generalisation | Smallest conjunction, impact test, depth tiers |
| AI-generated rule is wrong | Risk classifier still denies suspicious pairs (demo 2) |

## 10. Evaluation

The synthetic data generator hides **ground-truth policies** (e.g. "kaprodi may read grades of their prodi"),
so the pipeline can be measured end to end.

| Component | Metric |
|---|---|
| HGNN | Link prediction AUC on validation set |
| Risk classifier | Minority-class F1, p99 latency |
| Similar-case search | Precision@k (neighbours covered by the hidden policy) |
| Whole pipeline | **Rule recovery rate**: share of appeal scenarios that produce a rule equivalent to the hidden policy |

## 11. Demo scenarios

| Demo | Story | Shows |
|---|---|---|
| 01 | A student swaps the ID in the URL to read a classmate's grades → 403 | Policy stops BOLA |
| 02 | An over-broad rule ("lecturers may read grades in their faculty") lets `dosen_andi`, a new lecturer with no relations, request `mhs_dewi`'s grades → policy ALLOW, AI DENY (risk 0.87 > 0.70) | AI can only tighten, even when a rule is wrong |
| 03 | `dosen_budi` (kaprodi IF) is denied, appeals, admin approves → HGNN finds `dosen_sari` (kaprodi SI) → LLM writes the kaprodi rule → Sari gets access without appealing | Appeals generalise to similar cases |

## 12. Requirements for the data generator (phase 2)

- Category tree, users, students, courses, and all edges in section 3.1.
- `pernah_akses` history from allowed requests.
- Hidden ground-truth policies for evaluation.
- Labelled policy-allowed requests (normal / suspicious) for the risk classifier.
- Appeal scenarios with expected rules.

## 13. References

- Yin et al., *A heterogeneous graph-based semi-supervised learning framework for access control decision-making*, World Wide Web 2024. Code: https://github.com/happyResearcher/ACHG-SSLF (GPL-3.0, not copied).
- Mai et al., *LLM-Based Fine-Grained ABAC Policy Generation*, ICISSP 2025.
- Zhang et al., *Robust Heterogeneous Graph Neural Networks against Adversarial Attacks*, AAAI 2022.
