# Appeal feature: test report

Tests of the appeal feature after merging Vien's `feat/ai-corax-appeals` (commits `c4b4492`, `c61302c`) into branch
`fred`, with the demo stack adapted to it. Run on 2026-10-21.

| | |
|---|---|
| Feature under test | ai-corax `POST /corax/appeals`, `GET /corax/appeals/{id}`, `POST /corax/appeals/{id}/confirm` (`appeals.py`), the admin JWT check in ai-corax (`auth.py`), the admin routes in `policy/corax`, the demo console |
| Stack | `deploy/docker-compose.yml`: Envoy 1.38.7, OPA 1.21.2 with opa-envoy-plugin, ai-corax (Python 3.13), demo app, console |
| Data | `scripts/make_enterprise.py`, seed 0: 230 nodes, 2,739 edges, 1,515 `accessed` |
| HGNN | `hgnn-job` with learning rate 0.01, patience 50: val AUC 0.966, calibrated risk threshold 0.995 |
| Host | Windows 11 + WSL2, Docker 29.8 (snap, `docker-compose` v5); unit tests on Python 3.14, OPA 1.21.2 |

## Summary

| Suite | What it covers | Result |
|---|---|---|
| Unit and API tests (`pytest tests`) | ai-corax (incl. Vien's appeal and auth tests), hgnn-job, scripts, policy and demo configuration | **209 passed** |
| OPA tests (`opa test policy deploy/demo-app/policy`) | Framework incl. the admin routes, demo application rules | **42/42** |
| End to end through the gateway | HTTP requests to Envoy → OPA → ai-corax / app on a fresh stack, plus direct calls to ai-corax | **73/74**, the one failure is finding 1 |
| Console in a browser | Headless Edge driven through the DevTools protocol, clicking like a user | **15/15** |

## Findings

1. **An appeal for access the user already has is accepted.** `POST /corax/appeals` for a pair the current policy
   already allows returns 201, writes a redundant exception and offers candidate patterns that generalise the current
   policy itself. Suggestion: answer 409 in `AppealService.create` when `graph.has_access(user, obj)`.
2. **With the default tier limits, every enterprise rule is "large".** No small-tier candidate was found among 400
   random denied pairs: the pairs a rule opens are unusual for the HGNN by nature, so their mean risk (0.6 to 0.99) is
   above `AUTO_APPLY_MAX_MEAN_RISK` = 0.5, and most rules open more than 50 pairs. Every rule therefore needs
   `acknowledge_scope`. The small path was tested with raised limits (`AUTO_APPLY_MAX_PAIRS=100`,
   `AUTO_APPLY_MAX_MEAN_RISK=0.9`).
3. **"Narrowest first" can rank an appellant-only pattern first.** For `employee_E040 → document_D080`, candidate #1
   is "user located_in site_frankfurt AND user member_of team_engineering2": it matches only E040 and opens all
   83 documents for him. Its tier is large (83 pairs, mean risk 0.99), so it needs `acknowledge_scope`, but an admin
   could still confirm it by mistake. A possible change in `patterns.py`: drop or flag candidates whose only user is the
   appellant, or rank by kNN support.
4. **Fixed in the deployment: OPA did not start.** OPA loads `/runtime/generated` at start, but `AppealService` creates
   the folder only when it writes the first file, so OPA exited ("stat /runtime/generated: no such file or directory")
   and Envoy, with `failure_mode_allow: false`, denied every request. `deploy/ai-corax.Dockerfile` now creates the
   folder before ai-corax starts; creating it in `AppealService.__init__` would fix it for any deployment.
5. **Fixed in the console:** it read the admins from `config.admins`; it now reads `config.admin.users`.
6. **OPA picks up file changes quickly.** An exception was effective at the first poll after the appeal (under
   0.25 s); deleting a rule or exception file revoked the access within 0.3 s.

## End to end (74 checks)

Requests go to Envoy at `:8180` with JWTs signed like the console does; the "ai-corax checks the JWT" checks call
ai-corax inside its container, bypassing Envoy and OPA. Files and records are read inside the ai-corax container.

| Area | Checks | What is verified |
|---|---|---|
| Only admins pass the gateway | 8 | `POST /corax/appeals` without a token, as an employee, with a forged signature, an expired token or a wrong audience: 403. Employees get 403 on `GET` and `confirm`. Nothing is written |
| ai-corax checks the JWT itself | 8 | Called directly: no token, wrong signature, expired, wrong audience, no `exp`: 401; a valid employee token: 403 on `POST` and `GET`. Nothing is written |
| Input validation | 7 | Empty user, missing object, missing action: 422. Unknown user, object or appeal: 404. Nothing is written |
| Manager appeal (large, acknowledged) | 21 | 201 with a server-assigned `appeal-NNNN`; exception written and effective at once, only for that pair; candidate out of range or 0: 422; the expected rule is a candidate; confirming it without `acknowledge_scope` → 409 with the scope, nothing written; with it → `rule_applied` after syntax, whitelist, app tests and equivalence; the Engineering manager gets access through the rule; a second confirm or `candidate: null` afterwards: 409; `GET` shows the history (created, exception_applied, rule_applied, each by `admin_01`); the rule file records `approved_by` |
| Security officer appeal (large, acknowledged) | 4 | Rule applied; an opened pair with low risk (0.35) is allowed; an opened pair with risk 1.000 > 0.995 is denied by the AI check; the appellant's own pair passes (exception, no AI check) |
| One-off appeal (exception only) | 4 | `candidate: null` → `exception_only`; only the exception file exists; the engineer gets exactly that pair; confirming a candidate afterwards: 409 |
| BOLA | 1 | The BOLA request stays denied after all appeals |
| Revocation | 3 | Deleting the rule file denies the Engineering manager again; the exception still works; deleting the exception file denies the appellant again |
| Restart | 3 | An open appeal survives `docker restart` of ai-corax and can then be confirmed; ids continue after the restart |
| Concurrency | 4 | Five appeals at the same time: all created, five different ids, five exception files, five records |
| Odd URLs | 6 | `..%2F..%2Fstate%2Fx/confirm` 404, `%2e%2e/confirm` 404, `a/b/confirm` 403, `A%00x` 404, a 300-character id 404; nothing written |
| Access already held | 2 | The pair is allowed today; the appeal is still accepted (**fails**, finding 1) |
| Small tier | 3 | With raised limits, confirming the manager rule needs no acknowledgement; the rule opens access |

## Console in a browser (15 checks)

| Step | Verified |
|---|---|
| Page load | People (grouped by role) and the 7 + 3 scenario buttons load; the policy panel and the activity log fill |
| Case 1 | The BOLA scenario shows 403 "No rule allows it"; a high-risk pair shows 403 "OPA yes, ai-corax no" with the risk |
| Appeal as an employee | 403 from the gateway, "only admins may handle appeals" |
| Appeal as the admin | The pair is denied before; the exception is listed at once and the employee can read the document; the candidate table appears |
| Pick a large pattern | ai-corax answers 409; the console shows the tier, the reasons and "Confirm large scope"; after it: "Rule applied" with ✓ syntax, whitelist, app tests, equivalence, and the rule file in the policy panel |
| Keep only the exception | "Reject: keep only the exception" → "Only the exception: nothing generalised" |
| Activity log | Shows appeal created, exception written, rule written, kept only the exception, each by `admin_01` |

## How to reproduce

```bash
pip install -r hgnn-job/requirements.txt -r ai-corax/requirements.txt -r requirements-dev.txt
python scripts/demo_gateway.py prepare
CORAX_GATEWAY_PORT=8180 CORAX_CONSOLE_PORT=8190 docker-compose -p corax-next -f deploy/docker-compose.yml up -d --build
python scripts/demo_gateway.py run --gateway http://localhost:8180
OPA_PATH=<opa binary> python -m pytest tests
opa test policy deploy/demo-app/policy
```

The end-to-end and browser test scripts used for this report are not in the repository.
