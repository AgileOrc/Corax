# Security

## Invariants

1. `allow = policy_allow AND NOT ai_high_risk`: the risk score can only turn an allow into a deny.
2. Rules from appeals only define `allow` in `app.generated` or `app.exceptions` and live only in
   `policies/generated/`.
3. Every rule records its origin: appeal id, pattern, scope and tier. The appeal record keeps the
   similar cases, the candidates and the history.
4. Access granted by a rule from an appeal still goes through the risk score. Only the exact pair an
   admin approved skips it.
5. Policies change only through files. OPA's REST API is not used for writes and is not exposed.

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| A socially engineered appeal gets generalized | A human admin approves every appeal and picks the pattern. Large rules need a second confirmation |
| Over-generalization | Candidates come only from the appellant's facts, narrowest first, with the exact users and pairs shown, within tier limits |
| A wrong rule from an appeal | Equivalence check against the approved pattern. The risk score still denies pairs that do not fit the graph |
| Graph poisoning [[5]](evaluation.md#references) | `accessed` edges come only from allowed requests. The risk score checks newly opened pairs (mean risk in the tier) |
| A rule tries to make someone an admin or touch other policy | Whitelist: only `allow` in the two appeal packages, only fixed input and graph references. `corax.*` actions ignore those packages |
| Non-admin calls `/corax/appeals` | OPA allows `corax.*` actions only for `config.admin.users`. No application or appeal rule can grant them |
| Someone reaches the service directly, bypassing Envoy and OPA | The service verifies the admin's JWT itself (same key, `iss`, `aud` and admin list as OPA, read from the same `data.json`, algorithm fixed by key type, `exp` and `sub` required). `/risk` must stay on the internal network |
| Forged identity header (`x-corax-user`) | Ignored by the service. The audit log takes the admin from the verified JWT |
| Rego injection through ids in an appeal | Ids are written as JSON string literals and appeal ids are checked against a fixed pattern. The whitelist rejects anything else |
| The AI service is down or slow | The policy decision stands (`allowed without AI check`), never a silent allow beyond policy |

## Scope

**In scope:** object-level authorization (BOLA), centralized policy-as-code (ABAC + ReBAC), an AI risk
check that only tightens decisions, appeals that turn an admin's decision into a validated rule.

**Out of scope:**
- Broken Object Property Level Authorization (BOPLA): field-level response filtering and mass-assignment blocking.
- Policy changes without human approval.
- Production hardening (HA, multi-cluster).

## Known limitations

- The risk score is about pairs, not behavior over time. It does not detect fast enumeration by an
  otherwise legitimate user.
- Hard cases (an object a peer has) are caught less often than random ones. Read [evaluation](evaluation.md).

## Future work

- Production deployment: JWKS, TLS between Envoy, OPA and the service, health checks.
- Behavior features (request rate) to detect enumeration by an otherwise legitimate user.
- Inductive node features, so new users and objects get a risk score without retraining.
- Mini-batch training for graphs that do not fit in memory.
- Ranking candidates by how varied the similar cases are, so object-only slices rank lower.
- Category depth (distance from the root of an organization tree) as an extra tier input, where such a tree exists.
- Calibrated tier limits. The limits on the share of users, new pairs and mean risk are design defaults, not measured values, and no standard fixes them. Derive them from rules known to be correct and rules known to be too broad, and allow the pairs limit as a share of existing access.
- Policy languages other than Rego. The graph, the risk score and the appeal flow do not depend on Rego. Only the rule writer, its validation and the enforcement point do.
