# Corax

**AI-assisted, policy-as-code authorization for REST APIs. Stops Broken Object Level Authorization (BOLA) with deterministic policies, adds an AI layer that can only tighten decisions, and turns admin decisions into new policy rules.**

> Status: work in progress.

---

## Why

Authorization checks in APIs are usually written ad hoc inside each service. They are inconsistent between developers, undocumented, and hard to audit, which is why BOLA (OWASP API1) keeps happening.

Pure machine-learning access control is not the answer either: models are hard to update when rules change, can "forget" old decisions, and can be fooled by manipulated attributes.

Corax keeps **policy code as the source of truth** and uses AI only where it helps:

| Layer | Role | Can it grant access? |
|---|---|---|
| Policy code (OPA / Rego) | Final authority, deterministic | Yes |
| AI risk check (per request) | Flags suspicious requests that passed policy | **No, it can only deny** |
| AI rule suggestion (admin flow) | Finds similar cases when an admin approves an appeal, writes a rule | Only through a validated rule; broad grants need a human |

---

## How it works

### 1. Request path (every request)

```
Client ──► Envoy (PEP) ──► OPA (PDP, policy code)
                             │  deny  ──────────────────────────► 403
                             │  allow ↓
                             └──► AI-Corax /risk   risk = 1 − σ(h_user · h_object)
                                    low risk  → forward to the application
                                    high risk → 403, logged
```

- User identity comes **only from a verified JWT**, object ID from the URL path. Both are handled in Rego. Attributes are never taken from the request body.
- OPA only asks AI-Corax after the policy allowed the request, and the final rule is `allow = base_allow AND NOT ai_high_risk`, so the AI can only deny.
- If AI-Corax errors or times out, the policy decision stands and the event is logged.
- If OPA is down, Envoy denies everything (`failure_mode_allow: false`).

### 2. Admin path (when an admin approves an appeal)

```
Lecturer Budi (head of study program IF) is denied a student's grades, appeals, admin approves
   │
   ▼
Exact exception for Budi applied immediately
   │
   ▼
HGNN embeddings ──► nearest similar (lecturer, student) pairs that policy still denies
   │                 (e.g. Sari, head of study program SI, and her students)
   ▼
Pattern miner ──► shared attributes/relations (e.g. position = head of program, same study program)
   │
   ▼
Tier check (category-tree depth + affected users)
   │
   ├─ small scope → continue automatically
   └─ large scope → waits for admin confirmation
   ▼
Local LLMs write a Rego rule (mixture of agents, majority vote)
   │
   ▼
Validation (opa check, attribute whitelist, opa test, equivalence with the approved pattern)
   │
   ▼
Rule written to policies/generated/ ──► OPA reloads (--watch), everything logged
```

**Risk tiers.** Users are grouped in a category tree (root → lecturer/student → faculty → study program → position). A pattern is scored by the **depth** of the lowest common category it covers and the **number of users** under it. Shallow, large scopes need admin confirmation; deep, small scopes are applied automatically. A rule is revoked by deleting its file.

The full AI design, including how it maps to the papers below, is in [docs/ai-design.md](docs/ai-design.md).

---

## Architecture

| Component | Tech | Notes |
|---|---|---|
| `demo-api` | Python, FastAPI | Deliberately BOLA-vulnerable campus API |
| `sidecar` | Envoy (`ext_authz`) | One per service |
| `policy-engine` | OPA with `opa-envoy-plugin` (Rego) | JWT check, path parsing, policy; loads `policies/` with `--watch` |
| `corax-service` | Python, FastAPI | `/risk` (per-request risk score) and `/appeals` (similar cases → new rule) |
| `hgnn` | PyTorch Geometric (heterogeneous GraphSAGE) | Recomputes embeddings periodically and writes them to a folder that `corax-service` reads; reimplemented from Yin et al. 2024 |
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
| `CORAX_MODEL_DIR` | `output/hgnn` | Folder written by `hgnn` (embeddings, node ids, metadata) |
| `AI_RISK_THRESHOLD` | from `metadata.json` | Optional override; above this, a policy-allowed request is denied |
| `AI_TIMEOUT_MS` | `20` | Max time for the AI check |
| `AI_ON_ERROR` | `follow_policy` | What to do if the model fails |
| `AUTO_APPLY_MAX_USER_SHARE` | `0.4` | Max share of all users (0–1) that an appeal rule may grant new access to without admin confirmation |
| `AUTO_APPLY_MAX_PAIRS` | `50` | Max new (user, object) pairs for automatic grants |
| `AUTO_APPLY_MAX_MEAN_RISK` | `0.5` | Max mean AI risk of the new pairs for automatic grants |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Local LLM endpoint |
| `LLM_MODELS` | `qwen2.5-coder:7b,llama3.1:8b` | Models used as rule generators (majority vote) |

---

## Repository layout

```
.
├── hgnn/              # trains the HGNN, exports embeddings
├── service/           # /risk and /appeals service
├── policy/            # generic Rego framework (JWT, risk call, deny-only rule)
├── deploy/            # envoy.yaml, docker-compose.yml
├── scripts/           # helpers, e.g. dataset converters
├── docs/              # design documents and data format
└── tests/
```

The campus demo (vulnerable API, campus policies, synthetic data, demo scripts) lives in a separate repository, Corax-Demo.

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
