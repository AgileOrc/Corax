# Corax

**AI-assisted, policy-as-code authorization for REST APIs. Stops Broken Object Level Authorization (BOLA) with deterministic policies, adds an AI layer that can only tighten decisions, and turns admin decisions into new policy rules.**

> Status: work in progress. Built for Black Hat Arsenal.

---

## Why

Authorization checks in APIs are usually written ad hoc inside each service. They are inconsistent between developers, undocumented, and hard to audit, which is why BOLA (OWASP API1) keeps happening.

Pure machine-learning access control is not the answer either: models are hard to update when rules change, can "forget" old decisions, and can be fooled by manipulated attributes.

Corax keeps **policy code as the source of truth** and uses AI only where it helps:

| Layer | Role | Can it grant access? |
|---|---|---|
| Policy code (OPA / Rego) | Final authority, deterministic | Yes |
| AI risk check (per request) | Flags suspicious requests that passed policy | **No, it can only deny** |
| AI rule suggestion (admin flow) | Finds similar cases when an admin approves an appeal, writes a rule | Only through a validated, expiring rule; broad grants need a human |

---

## How it works

### 1. Request path (every request)

```
Client ──► Envoy sidecar ──► authz-service ──► OPA (policy code)
                                   │              deny  → 403
                                   │              allow ↓
                                   └──► AI risk check (classifier on HGNN embeddings)
                                          low risk  → forward to service
                                          high risk → 403 / step-up, logged
```

- User identity comes **only from a verified JWT**, object ID from the URL path. Attributes are never taken from the request body.
- If the AI model errors or times out, the policy decision stands and the event is logged.
- If `authz-service` itself is down, Envoy denies everything (`failure_mode_allow: false`).

### 2. Admin path (when an admin changes one decision)

```
Lecturer Budi (head of study program IF) is denied a student's grades, appeals, admin approves
   │
   ▼
HGNN embeddings ──► nearest similar (lecturer, student) pairs that policy still denies
   │                 (e.g. Sari, head of study program SI, and her students)
   ▼
Pattern miner ──► shared attributes/relations (e.g. position = head of program, same study program)
   │
   ▼
Local LLMs draft a Rego rule (mixture of agents, majority vote)
   │
   ▼
Validation (opa check, attribute whitelist, opa test) ──► impact test on historical requests
   │                                                      ("changes 47 decisions for 14 users")
   ▼
Decision engine (category-tree depth, affected users, sensitivity, risk score of newly opened pairs)
   │
   ├─ deep / small scope → applied automatically, with expiry, logged, revocable
   └─ broad grant        → waits for admin approval
   ▼
Rule written to policies/generated/ ──► OPA reloads (--watch)
```

**Risk tiers.** Users are grouped in a category tree (root → lecturer/student → faculty → study program → position). A proposed rule is scored by the **depth** of the lowest common category it covers and the **number of users** under it. Shallow, large scopes need approval; deep, small scopes are applied automatically with an expiry (7 days, or 24 hours for faculty-wide rules). The expiry is checked inside the Rego rule itself.

The full AI design, including how it maps to the papers below, is in [docs/ai-design.md](docs/ai-design.md).

---

## Architecture

| Component | Tech | Notes |
|---|---|---|
| `demo-api` | Python, FastAPI | Deliberately BOLA-vulnerable campus API |
| `sidecar` | Envoy (`ext_authz`) | One per service |
| `authz-service` | Python, FastAPI | Core of the tool: policy call + AI check |
| `policy-engine` | OPA (Rego) | Loads `policies/` with `--watch` |
| `embedding-store` | Redis | HGNN embeddings |
| `hgnn-job` | PyTorch Geometric (heterogeneous GraphSAGE) | Recomputes embeddings periodically; reimplemented from Yin et al. 2024 |
| `rule-suggester` | Python, scikit-learn | Nearest neighbours, pattern miner, validation, impact test, decision engine |
| `llm` | Ollama (local models) | Writes Rego rules from mined patterns; reimplements Mai et al. 2025 |
| `data-generator` | Python, Faker | Synthetic users, relations, category tree, labelled access logs |

---

## Quick start

```bash
git clone https://github.com/<you>/Corax.git
cd Corax
docker compose up --build
```

The demo API is exposed through the sidecar at `http://localhost:8080`.

<!-- TODO: fill in once the demo scripts exist -->
```bash
# 1. BOLA attempt blocked by policy
./demo/01_bola_blocked.sh

# 2. Over-broad rule lets a request through policy, AI risk check denies it
./demo/02_broad_rule_caught.sh

# 3. Admin exception -> similar cases -> proposed rule -> impact test
./demo/03_rule_suggestion.sh
```

---

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `POLICY_ENGINE_URL` | `http://policy-engine:8181` | OPA endpoint |
| `EMBEDDING_STORE` | `redis://embedding-store:6379` | Embedding store |
| `AI_RISK_THRESHOLD` | `0.7` | Above this, a policy-allowed request is denied |
| `AI_TIMEOUT_MS` | `20` | Max time for the AI check |
| `AI_ON_ERROR` | `follow_policy` | What to do if the model fails |
| `AUTO_APPLY_MAX_USERS` | `5` | Max affected users for automatic grants |
| `AUTO_APPLY_MIN_DEPTH` | `3` | Min category-tree depth for automatic grants |
| `AUTO_RULE_EXPIRY_DAYS` | `7` | Auto-applied rules expire unless approved |
| `AUTO_RULE_EXPIRY_BROAD_HOURS` | `24` | Expiry for auto-applied faculty-wide rules |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Local LLM endpoint |
| `LLM_MODELS` | `qwen2.5-coder:7b,llama3.1:8b` | Models used as rule generators (majority vote) |

---

## Repository layout

```
.
├── demo-api/          # vulnerable campus API
├── authz-service/     # policy + AI decision logic
├── hgnn-job/          # embedding training/inference
├── rule-suggester/    # similar cases → Rego rules → impact test
├── data-generator/    # synthetic dataset
├── policies/          # Rego policies (human-written + generated/ rules)
├── docs/              # design documents
├── envoy.yaml
└── docker-compose.yml
```

---

## Scope

**In scope:** object-level authorization (BOLA), centralized policy-as-code (ABAC + ReBAC), AI-assisted rule suggestion, AI risk check that only tightens decisions.

**Out of scope (roadmap):**
- Broken Object Property Level Authorization (BOPLA): field-level response filtering and mass-assignment blocking
- Fully autonomous (agentic) policy changes without human approval
- Production hardening (HA, multi-cluster)

---

## Related work

- Nobi et al., *Toward Deep Learning Based Access Control*, ACM CODASPY 2022
- Nobi et al., *Administration of Machine Learning Based Access Control*, ESORICS 2022
- You et al., *A knowledge graph empowered online learning framework for access control decision-making*, World Wide Web 2023
- Yin et al., *A heterogeneous graph-based semi-supervised learning framework for access control decision-making*, World Wide Web 2024 ([code](https://github.com/happyResearcher/ACHG-SSLF); Corax reimplements the method and does not copy code)
- Zhang et al., *Robust Heterogeneous Graph Neural Networks against Adversarial Attacks*, AAAI 2022
- Mai et al., *LLM-Based Fine-Grained ABAC Policy Generation*, ICISSP 2025

---

## Disclaimer

`demo-api` is intentionally vulnerable. Run it only in an isolated environment.

## License

<!-- TODO: choose an open-source license, e.g. Apache-2.0 or MIT -->