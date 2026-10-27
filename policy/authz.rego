# Corax decision: allow = admin_allow OR exception_allow OR (policy_allow AND NOT ai_high_risk).
#
# admin_allow covers Corax's own admin routes (corax.* actions, e.g. appeals): only users listed in
# config.admin.users may call them, and nothing else (application rules, appeal rules) can grant them.
#
# policy_allow comes from the application's own rules (package app.authz) or from rules added
# through appeals (package app.generated, files in policies/generated/). exception_allow comes from
# the exact pair an admin approved in an appeal (package app.exceptions); it skips the AI check
# because the admin already reviewed it. All of them see the normalised request from request.rego.
#
# The AI risk check runs only after the policy allowed the request, so it can only turn an allow
# into a deny. If corax-service errors or times out, the policy decision stands.
#
# Entry points:
#   allow    boolean
#   result   object for opa-envoy-plugin: allowed, headers (x-corax-user for the upstream service)
#            and dynamic_metadata (reason, risk) for Envoy logs
package corax.authz

default allow := false

allow if admin_allow

allow if self_allow

allow if exception_allow

allow if {
	policy_allow
	not ai_high_risk
}

corax_action if startswith(request.action, "corax.")

admin_allow if {
	corax_action
	user_id in object.get(object.get(config, "admin", {}), "users", [])
}

# Any user with a valid token may list their own access. The service takes the user from the same
# token, so this never shows another user's access.
self_allow if {
	request.action == "corax.me.access"
	user_id
}

exception_allow if {
	not corax_action
	data.app.exceptions.allow with input as request
}

policy_allow if {
	not corax_action
	data.app.authz.allow with input as request
}

policy_allow if {
	not corax_action
	data.app.generated.allow with input as request
}

# --- AI risk check ---------------------------------------------------------

# Called only when the policy allowed the request, it is not an appeal exception,
# and the route has a resource id.
risk_response := http.send({
	"method": "POST",
	"url": concat("", [config.ai.url, "/risk"]),
	"headers": {"Content-Type": "application/json"},
	"body": {"user": request.user.id, "object": request.resource.id, "action": request.action},
	"timeout": object.get(config.ai, "timeout", "20ms"),
	"raise_error": false,
}) if {
	policy_allow
	not exception_allow
}

# An appeal exception skips the risk check, so the service is told separately that the access was
# used, for the admin's usage log. The answer never changes the decision.
usage_response := http.send({
	"method": "POST",
	"url": concat("", [config.ai.url, "/usage"]),
	"headers": {"Content-Type": "application/json"},
	"body": {"user": request.user.id, "object": request.resource.id, "action": request.action},
	"timeout": object.get(config.ai, "timeout", "20ms"),
	"raise_error": false,
}) if {
	exception_allow
	config.ai.url
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
} else := "admin action" if {
	admin_allow
} else := "own access list" if {
	self_allow
} else := "admin only" if {
	corax_action
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

default usage_metadata := {}

usage_metadata := {"corax_usage_logged": usage_response.status_code == 200} if usage_response

# The verified user id is passed to the upstream service (corax-service uses it for the appeal audit log).
default headers := {}

headers := {"x-corax-user": user_id} if allow

result := {
	"allowed": allow,
	"headers": headers,
	"dynamic_metadata": object.union(object.union({"corax_reason": reason}, risk_metadata), usage_metadata),
}
