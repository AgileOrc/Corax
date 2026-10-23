# Rules of the dummy campus (scripts/prepare/make_dummy.py), the application's own policy for the demo.
# Corax's framework (policy/) evaluates them with the normalised request as input:
#   {"user": {"id": ...}, "action": "read_grades" | "read_profile", "resource": {"type": "student", "id": ...}}
# The campus facts come from graph.json, loaded by OPA as data.corax.graph.
package app.authz

graph := data.corax.graph

# A lecturer reads the grades of a student who takes a course they teach ...
allow if {
	input.action == "read_grades"
	some course in graph[input.user.id].teaches
	course in graph[input.resource.id].enrolled_in
}

# ... or of a student they advise. Nothing covers heads of program yet: that rule comes from an appeal.
allow if {
	input.action == "read_grades"
	input.resource.id in graph[input.user.id].advises
}

# Deliberately too broad: every lecturer may read every student's profile.
# The policy allows it; the AI risk check denies the pairs that do not fit the access graph.
allow if {
	input.action == "read_profile"
	count(object.get(graph, [input.user.id, "holds"], [])) > 0
}
