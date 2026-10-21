# Appeal feature: test report

Tests of the appeal feature on branch `feat/appeals-api-and-demo` (commit `979bb2f`, plus the fix in finding 1), run on
2026-10-21.

| | |
|---|---|
| Feature under test | `POST /appeals`, `POST /appeals/{id}/pick`, `/confirm`, `/reject`, `GET /appeals/{id}` (`ai-corax/appeals.py`), the admin routes in OPA (`policy/corax/admin.rego`), the demo console |
| Stack | `deploy/docker-compose.yml`: Envoy 1.38.7, OPA 1.21.2 with opa-envoy-plugin, ai-corax (Python 3.13), demo app, console |
| Data | `scripts/make_enterprise.py`, seed 0: 230 nodes, 2,739 edges, 1,515 `accessed` |
| HGNN | `hgnn-job` with learning rate 0.01, patience 50: val AUC 0.966, calibrated risk threshold 0.995 |
| Host | Windows 11 + WSL2, Docker 29.8 (snap, `docker-compose` v5); unit tests on Python 3.14, OPA 1.21.2 |

## Summary

| Suite | What it covers | Result |
|---|---|---|
| Unit and API tests (`pytest tests`) | ai-corax (incl. 19 appeal tests), hgnn-job, scripts, policy | **189 passed** |
| OPA tests (`opa test policy deploy/demo-app/policy`) | Framework incl. the admin routes, demo application rules | **41/41** |
| End to end through the gateway | HTTP requests to Envoy → OPA → ai-corax / app, on a fresh stack | **78/78** |
| Console in a browser | Headless Edge driven through the DevTools protocol, clicking like a user | **15/15** |

## Findings

1. **Fixed: an appeal for access the user already has was accepted.** ai-corax wrote a redundant exception and offered
   candidate patterns that generalise the current policy itself. It now answers `409` ("already has access: nothing to
   appeal"); `ai-corax/appeals.py` and a unit test changed after commit `979bb2f`.
2. **With the default tier limits, every enterprise rule is "large".** No small-tier candidate was found among 400
   random denied pairs: the pairs a rule opens are unusual for the HGNN by nature, so their mean risk (0.6 to 0.99) is
   above `AUTO_APPLY_MAX_MEAN_RISK` = 0.5, and most rules open more than 50 pairs. Every generalisation therefore waits
   for an admin. The small-tier path was tested with raised limits (`AUTO_APPLY_MAX_PAIRS=100`,
   `AUTO_APPLY_MAX_MEAN_RISK=0.9`). Worth a look when the limits are calibrated.
3. **"Narrowest first" can rank an appellant-only pattern first.** Candidates are ordered by the number of pairs they
   open. For the appeal `employee_E040 → document_D080`, candidate #1 is "user located_in site_frankfurt AND user
   member_of team_engineering2": it matches only E040 and opens all 83 documents for him. The tier is large (83 pairs,
   mean risk 0.99), so it cannot pass without a confirmation, but an admin could pick it by mistake. A possible change
   in `patterns.py`: drop or flag candidates whose only user is the appellant, or rank by kNN support.
4. **OPA picks up file changes quickly.** An exception was effective at the first poll after the appeal (under
   0.25 s); deleting a rule or exception file revoked the access within 0.3 s.
5. Cosmetic: the console said "1 users"; fixed.

## End to end through the gateway (78 checks)

All requests go to Envoy at `:8180` with JWTs signed like the console does; files and the audit log are read inside
the ai-corax container.

| Area | Checks | What is verified |
|---|---|---|
| Only admins | 10 | `POST /appeals` without a token, as an employee, with a forged signature, an expired token or a wrong audience: 403. Employees get 403 on `GET /appeals/x`, `pick`, `confirm`, `reject`. Nothing is written |
| Input validation | 8 | Appeal id with a path, empty user, missing object, action with quotes: 422. Unknown user, object or appeal: 404. Nothing is written |
| Manager appeal (large, confirmed) | 23 | Exception written and effective at once, only for that pair; duplicate id 409; confirm before a pick 409; pick out of range 400, pick 0 422; the expected rule is a candidate; pick → `awaiting_confirmation` with reasons, no rule file yet; confirm → `applied` after syntax, whitelist, app tests and equivalence; the Engineering manager gets access through the rule; second confirm, reject after applying: 409; `GET` shows the state and who confirmed |
| Security officer appeal (large, confirmed) | 4 | Rule applied; an opened pair with low risk (0.35) is allowed; an opened pair with risk 1.000 > 0.995 is denied by the AI check; the appellant's own pair passes (exception, no AI check) |
| One-off appeal (rejected at the choice) | 5 | Rejected before any pick; only the exception file exists; the engineer gets exactly that pair; pick after reject 409 |
| Large rule rejected at confirmation | 4 | Pick → `awaiting_confirmation` → reject → `rejected`; no rule file; the BOLA request stays denied |
| Audit log | 2 | The manager appeal's events in order (approved, exception_applied, candidates, picked, awaiting_confirmation, confirmed, rule_applied), each with the admin's name |
| Revocation | 3 | Deleting the rule file denies the Engineering manager again; the exception still works; deleting the exception file denies the appellant again |
| Restart | 3 | An appeal waiting for confirmation survives `docker restart` of ai-corax and can then be confirmed |
| Concurrency | 4 | Five appeals at the same time: all accepted, five exception files, five state files, five audit entries |
| Odd URLs | 6 | `/appeals/..%2F..%2Fstate%2Fx/pick` 404, `/appeals/%2e%2e/pick` 400, `/appeals/a/b/pick` 403, `/appeals/A%00x` 400, a 300-character id 400; nothing written |
| Access already held | 2 | The pair is allowed today; the appeal is refused with 409 (finding 1) |
| Small tier | 4 | With raised limits, picking the manager rule applies it at once (no confirmation), the file is written and opens access |

## Console in a browser (15 checks)

| Step | Verified |
|---|---|
| Page load | People (grouped by role) and the 7 + 3 scenario buttons load; the policy panel and the activity log fill |
| Case 1 | The BOLA scenario shows 403 "No rule allows it"; a high-risk pair shows 403 "OPA yes, ai-corax no" with the risk |
| Appeal as an employee | 403 from the gateway, "only admins may handle appeals" |
| Appeal as the admin | The pair is denied before; the exception is listed at once and the employee can read the document; the candidate table appears |
| Pick and confirm | Picking #1 shows the tier, the reasons and the Rego; Confirm → "Rule applied" with ✓ syntax, whitelist, app tests, equivalence; the rule file appears in the policy panel |
| Reject | "Reject: keep only the exception" → "Rejected: only the exception applies" |
| Activity log | Shows approved, exception written, pattern picked, rule written, rejected |

## How to reproduce

```bash
python scripts/demo_gateway.py prepare
CORAX_GATEWAY_PORT=8180 CORAX_CONSOLE_PORT=8190 docker-compose -p corax-next -f deploy/docker-compose.yml up -d --build
OPA_PATH=<opa binary> python -m pytest tests
opa test policy deploy/demo-app/policy
```

The end-to-end and browser test scripts used for this report are not in the repository.
