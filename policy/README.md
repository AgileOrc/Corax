# policy

Generic Rego framework shared by every application that uses Corax. Not built yet.

- Verifies the JWT and parses the request path.
- Calls `ai-corax` `/risk` only when the application's own rules allow the request.
- Final decision: `allow = base_allow AND NOT ai_high_risk`.
- Includes AI-generated rules from the application's `policies/generated/` folder.

Application-specific rules (`base_allow`) live in the application's repository,
e.g. the campus rules in Corax-Demo.
