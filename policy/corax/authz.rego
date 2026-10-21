# Corax decision: allow = exception_allow OR (policy_allow AND NOT ai_high_risk).
#
# policy_allow comes from the application's own rules (package app.authz) or from rules added
# through appeals (package app.generated, files in policies/generated/). exception_allow comes from
# the exact pair an admin approved in an appeal (package app.exceptions); it skips the AI check
# because the admin already reviewed it. All of them see the normalised request from request.rego.
#
# The AI risk check runs only after the policy allowed the request, so it can only turn an allow
# into a deny. If ai-corax errors or times out, the policy decision stands.
#
# Admin routes (ai-corax /appeals, admin.rego) are decided by admin_allow alone: the rules above
# never open them.
#
# Entry points:
#   allow    boolean
#   result   object for opa-envoy-plugin: allowed + dynamic_metadata (reason, risk) for Envoy logs
package corax.authz

default allow := false

allow if exception_allow

allow if {
	policy_allow
	not ai_high_risk
}

exception_allow if {
	not admin_route
	data.app.exceptions.allow with input as request
}

policy_allow if {
	not admin_route
	data.app.authz.allow with input as request
}

policy_allow if {
	not admin_route
	data.app.generated.allow with input as request
}

# --- AI risk check ---------------------------------------------------------

# Called only when the policy allowed the request, it is not an appeal exception,
# and the route has a resource id.
risk_response := http.send({
	"method": "POST",
	"url": concat("", [config.ai.url, "/risk"]),
	"headers": {"Content-Type": "application/json"},
	"body": {"user": request.user.id, "object": request.resource.id},
	"timeout": object.get(config.ai, "timeout", "20ms"),
	"raise_error": false,
}) if {
	policy_allow
	not exception_allow
}

ai_checked if risk_response.status_code == 200

ai_high_risk if {
	ai_checked
	risk_response.body.high_risk == true
}

ai_risk := risk_response.body.risk if {
	ai_checked
	is_number(risk_response.body.risk)
}

# --- Explanation --------------------------------------------------------------

reason := "missing or invalid token" if {
	not user_id
} else := "no matching route" if {
	not route
} else := "allowed admin request" if {
	admin_allow
} else := "admin only" if {
	admin_route
} else := "allowed by appeal exception" if {
	exception_allow
} else := "denied by policy" if {
	not policy_allow
} else := "high AI risk" if {
	ai_high_risk
} else := "allowed without AI check" if {
	not ai_checked
} else := "allowed"

default risk_metadata := {}

risk_metadata := {"corax_risk": ai_risk}

result := {
	"allowed": allow,
	"dynamic_metadata": object.union({"corax_reason": reason}, risk_metadata),
}
