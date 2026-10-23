# Security

## Invariants

1. `allow = policy_allow AND NOT ai_high_risk`: the risk score can only turn an allow into a deny.
2. Rules from appeals only define `allow` in `app.generated` or `app.exceptions` and live only in
   `policies/generated/`.
3. Every rule records its origin: appeal id, pattern, scope and tier; the appeal record keeps the
   similar cases, the candidates and the history.
4. Access granted by a rule from an appeal still goes through the risk score. Only the exact pair an
   admin approved skips it.
5. Policies change only through files; OPA's REST API is not used for writes and is not exposed.

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| A socially engineered appeal gets generalized | A human admin approves every appeal and picks the pattern; large rules need a second confirmation |
| Over-generalization | Candidates come only from the appellant's facts, narrowest first, with the exact users and pairs shown; tier limits |
| A wrong rule from an appeal | Equivalence check against the approved pattern; the risk score still denies pairs that do not fit the graph |
| Graph poisoning [[5]](../references.md) | `accessed` edges come only from allowed requests; the risk score checks newly opened pairs (mean risk in the tier) |
| A rule tries to make someone an admin or touch other policy | Whitelist: only `allow` in the two appeal packages, only fixed input and graph references; `corax.*` actions ignore those packages |
| Non-admin calls `/corax/appeals` | OPA allows `corax.*` actions only for `config.admin.users`; no application or appeal rule can grant them |
| Someone reaches the service directly, bypassing Envoy and OPA | The service verifies the admin's JWT itself (same key, `iss`, `aud` and admin list as OPA, read from the same `data.json`; algorithm fixed by key type; `exp` and `sub` required). `/risk` must stay on the internal network |
| Forged identity header (`x-corax-user`) | Ignored by the service; the audit log takes the admin from the verified JWT |
| Rego injection through ids in an appeal | Ids are written as JSON string literals and appeal ids are checked against a fixed pattern; the whitelist rejects anything else |
| The AI service is down or slow | The policy decision stands (`allowed without AI check`), never a silent allow beyond policy |
