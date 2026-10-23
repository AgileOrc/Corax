# The demo's decisions through Corax's framework: opa test policy/authz.rego policy/request.rego deploy/demo
# (not the whole policy/ folder: its config.example.json would clash with deploy/demo/data.json).
# Uses deploy/demo/data.json as the configuration and a small campus graph; corax-service is mocked.
package demo_test

import data.corax.authz

graph := {
	"lecturer_budi": {"holds": ["position_lecturer"], "member_of": ["program_IF"], "teaches": ["course_IF_1"]},
	"lecturer_sari": {"holds": ["position_head_of_program"], "member_of": ["program_IF"], "teaches": ["course_IF_2"]},
	"lecturer_andi": {"holds": ["position_lecturer"], "member_of": ["program_SI"], "advises": ["student_dewi"]},
	"student_ani": {"member_of": ["program_IF"], "enrolled_in": ["course_IF_1"]},
	"student_dewi": {"member_of": ["program_SI"], "enrolled_in": ["course_SI_1"]},
}

now_s := round(time.now_ns() / 1000000000)

request(method, path, user) := {"attributes": {"request": {"http": {
	"method": method,
	"path": path,
	"headers": {"authorization": concat(" ", ["Bearer", token(user)])},
}}}}

token(user) := io.jwt.encode_sign(
	{"typ": "JWT", "alg": "HS256"},
	{"sub": user, "iss": data.corax.config.jwt.iss, "aud": data.corax.config.jwt.aud, "exp": now_s + 600},
	{"kty": "oct", "k": base64url.encode_no_pad(data.corax.config.jwt.secret)},
)

risk_low(_) := {"status_code": 200, "body": {"risk": 0.1, "high_risk": false}}

risk_high(_) := {"status_code": 200, "body": {"risk": 0.999, "high_risk": true}}

test_teacher_reads_grades if {
	authz.allow with input as request("GET", "/students/student_ani/grades", "lecturer_budi")
		with data.corax.graph as graph
		with http.send as risk_low
}

test_advisor_reads_grades if {
	authz.allow with input as request("GET", "/students/student_dewi/grades", "lecturer_andi")
		with data.corax.graph as graph
		with http.send as risk_low
}

test_bola_is_denied_by_policy if {
	authz.reason == "denied by policy" with input as request("GET", "/students/student_dewi/grades", "lecturer_budi")
		with data.corax.graph as graph
		with http.send as risk_low
}

test_head_of_program_has_no_rule_before_the_appeal if {
	not authz.allow with input as request("GET", "/students/student_ani/grades", "lecturer_sari")
		with data.corax.graph as graph
		with http.send as risk_low
}

test_any_lecturer_passes_the_broad_profile_rule if {
	authz.allow with input as request("GET", "/students/student_dewi/profile", "lecturer_budi")
		with data.corax.graph as graph
		with http.send as risk_low
}

test_ai_denies_a_high_risk_profile_read if {
	authz.reason == "high AI risk" with input as request("GET", "/students/student_dewi/profile", "lecturer_budi")
		with data.corax.graph as graph
		with http.send as risk_high
}

test_students_have_no_profile_access if {
	not authz.allow with input as request("GET", "/students/student_dewi/profile", "student_ani")
		with data.corax.graph as graph
		with http.send as risk_low
}

test_only_the_demo_admin_may_appeal if {
	authz.allow with input as request("POST", "/corax/appeals", "admin_rina")
		with data.corax.graph as graph
	not authz.allow with input as request("POST", "/corax/appeals", "lecturer_sari")
		with data.corax.graph as graph
}
