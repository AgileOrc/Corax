package corax.authz_test

import data.corax.authz

# --- Fixtures ---------------------------------------------------------------

secret := "test-secret"

fixture_config := {
	"jwt": {"secret": secret, "iss": "test-issuer", "aud": "test-api"},
	"routes": [
		{
			"method": "GET",
			"path": "/students/:id/grades/:course_code",
			"action": "read_grades",
			"resource_type": "student",
		},
		{"method": "GET", "path": "/students/:id", "action": "read_personal_data", "resource_type": "student"},
	],
	"ai": {"url": "http://ai-corax.test", "timeout": "20ms"},
}

now_s := round(time.now_ns() / 1000000000)

valid_claims := {"sub": "alice", "iss": "test-issuer", "aud": "test-api", "exp": now_s + 3600}

sign(claims, key) := io.jwt.encode_sign(
	{"typ": "JWT", "alg": "HS256"},
	claims,
	{"kty": "oct", "k": base64url.encode_no_pad(key)},
)

envoy_input(method, path, authorization) := {"attributes": {"request": {"http": {
	"method": method,
	"path": path,
	"headers": {"authorization": authorization},
}}}}

# Alice, with a valid token, reads Bob's grades for IF201.
read_grades := envoy_input("GET", "/students/bob/grades/IF201", concat(" ", ["Bearer", sign(valid_claims, secret)]))

# ai-corax mocks
risk_low(_) := {"status_code": 200, "body": {"risk": 0.1, "high_risk": false}}

risk_high(_) := {"status_code": 200, "body": {"risk": 0.99, "high_risk": true}}

risk_unknown_user(_) := {"status_code": 200, "body": {"risk": null, "high_risk": false}}

risk_unreachable(_) := {"status_code": 0, "error": {"code": "eval_http_send_network_error"}}

# --- Request normalisation ----------------------------------------------------

test_request_from_token_and_path if {
	authz.request == {
		"user": {"id": "alice"},
		"action": "read_grades",
		"resource": {"type": "student", "id": "bob", "course_code": "IF201"},
	} with input as read_grades
		with data.corax.config as fixture_config
}

test_query_string_is_ignored if {
	token := concat(" ", ["Bearer", sign(valid_claims, secret)])
	authz.request == {
		"user": {"id": "alice"},
		"action": "read_personal_data",
		"resource": {"type": "student", "id": "bob"},
	} with input as envoy_input("GET", "/students/bob?user=mallory&id=carol", token)
		with data.corax.config as fixture_config
}

test_trailing_slash_matches if {
	token := concat(" ", ["Bearer", sign(valid_claims, secret)])
	authz.request.resource.id == "bob" with input as envoy_input("GET", "/students/bob/", token)
		with data.corax.config as fixture_config
}

# --- JWT ------------------------------------------------------------------------

deny_with_token(token) if {
	inp := envoy_input("GET", "/students/bob/grades/IF201", token)
	not authz.allow with input as inp
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with http.send as risk_low
	authz.reason == "missing or invalid token" with input as inp
		with data.corax.config as fixture_config
}

test_missing_token_denied if {
	deny_with_token("")
}

test_non_bearer_scheme_denied if {
	deny_with_token(concat(" ", ["Basic", sign(valid_claims, secret)]))
}

test_wrong_signature_denied if {
	deny_with_token(concat(" ", ["Bearer", sign(valid_claims, "other-secret")]))
}

test_expired_token_denied if {
	deny_with_token(concat(" ", ["Bearer", sign(object.union(valid_claims, {"exp": now_s - 60}), secret)]))
}

test_wrong_issuer_denied if {
	deny_with_token(concat(" ", ["Bearer", sign(object.union(valid_claims, {"iss": "evil"}), secret)]))
}

test_wrong_audience_denied if {
	deny_with_token(concat(" ", ["Bearer", sign(object.union(valid_claims, {"aud": "other-api"}), secret)]))
}

test_token_without_subject_denied if {
	deny_with_token(concat(" ", ["Bearer", sign(object.remove(valid_claims, ["sub"]), secret)]))
}

test_unsigned_token_denied if {
	header := base64url.encode_no_pad(json.marshal({"typ": "JWT", "alg": "none"}))
	payload := base64url.encode_no_pad(json.marshal(valid_claims))
	deny_with_token(concat("", ["Bearer ", header, ".", payload, "."]))
}

# --- Routes -----------------------------------------------------------------------

deny_route(method, path) if {
	inp := envoy_input(method, path, concat(" ", ["Bearer", sign(valid_claims, secret)]))
	not authz.allow with input as inp
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with http.send as risk_low
	authz.reason == "no matching route" with input as inp
		with data.corax.config as fixture_config
}

test_wrong_method_denied if {
	deny_route("DELETE", "/students/bob/grades/IF201")
}

test_unknown_path_denied if {
	deny_route("GET", "/admin/users")
}

test_extra_segment_denied if {
	deny_route("GET", "/students/bob/grades/IF201/extra")
}

test_empty_parameter_denied if {
	deny_route("GET", "/students//grades/IF201")
}

test_ambiguous_routes_denied if {
	both := object.union(fixture_config, {"routes": array.concat(fixture_config.routes, [{
		"method": "GET",
		"path": "/students/me",
		"action": "read_own_profile",
		"resource_type": "student",
	}])})
	inp := envoy_input("GET", "/students/me", concat(" ", ["Bearer", sign(valid_claims, secret)]))
	not authz.allow with input as inp
		with data.corax.config as both
		with data.app.authz.allow as true
		with http.send as risk_low
}

# --- Decision -----------------------------------------------------------------------

test_policy_deny_never_calls_ai if {
	not authz.allow with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as false
		with http.send as risk_high
	not authz.risk_response with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as false
		with http.send as risk_high
	authz.reason == "denied by policy" with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as false
}

test_no_application_rules_denied if {
	not authz.allow with input as read_grades
		with data.corax.config as fixture_config
		with http.send as risk_low
}

test_policy_allow_and_low_risk_allowed if {
	authz.allow with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with http.send as risk_low
	authz.result == {"allowed": true, "dynamic_metadata": {"corax_reason": "allowed", "corax_risk": 0.1}} with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with http.send as risk_low
}

test_policy_allow_and_high_risk_denied if {
	not authz.allow with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with http.send as risk_high
	authz.result == {"allowed": false, "dynamic_metadata": {"corax_reason": "high AI risk", "corax_risk": 0.99}} with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with http.send as risk_high
}

test_ai_unreachable_keeps_policy_decision if {
	authz.allow with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with http.send as risk_unreachable
	authz.reason == "allowed without AI check" with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with http.send as risk_unreachable
}

test_unknown_to_ai_keeps_policy_decision if {
	authz.allow with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with http.send as risk_unknown_user
	authz.result.dynamic_metadata == {"corax_reason": "allowed"} with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with http.send as risk_unknown_user
}

test_generated_rule_allows if {
	authz.allow with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as false
		with data.app.generated.allow as true
		with http.send as risk_low
}

test_generated_rule_still_goes_through_ai if {
	not authz.allow with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as false
		with data.app.generated.allow as true
		with http.send as risk_high
}

# The mock only answers the expected request; any other request leaves the AI check unanswered.
test_ai_request_uses_token_user_and_path_resource if {
	authz.reason == "allowed" with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with http.send as expect_alice_bob
}

expect_alice_bob(req) := {"status_code": 200, "body": {"risk": 0.1, "high_risk": false}} if {
	req.method == "POST"
	req.url == "http://ai-corax.test/risk"
	req.body == {"user": "alice", "object": "bob"}
}

# --- Appeal exceptions ---------------------------------------------------------------

test_exception_allows_when_policy_denies if {
	authz.allow with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as false
		with data.app.exceptions.allow as true
		with http.send as risk_low
}

test_exception_skips_ai_check if {
	authz.allow with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with data.app.exceptions.allow as true
		with http.send as risk_high
	not authz.risk_response with input as read_grades
		with data.corax.config as fixture_config
		with data.app.authz.allow as true
		with data.app.exceptions.allow as true
		with http.send as risk_high
}

test_exception_reason if {
	authz.result == {"allowed": true, "dynamic_metadata": {"corax_reason": "allowed by appeal exception"}} with input as read_grades
		with data.corax.config as fixture_config
		with data.app.exceptions.allow as true
}

test_exception_still_needs_valid_token if {
	inp := envoy_input("GET", "/students/bob/grades/IF201", concat(" ", ["Bearer", sign(valid_claims, "other-secret")]))
	not authz.allow with input as inp
		with data.corax.config as fixture_config
		with data.app.exceptions.allow as true
}
