# Rules of the demo application (the document app), written by people. scripts/prepare/make_enterprise.py
# records exactly what the reading rules allow as the access history.
#
# The input is the normalised request of policy/request.rego (the actions and resource types
# are those of the routes in demo/data.json); relations come from the graph that hgnn
# exports (data.corax.graph). Rules added through appeals live in app.generated and app.exceptions,
# never in this package.
package app.authz

# An employee is a node of the graph; the admins are those of demo/data.json.
employee if data.corax.graph[input.user.id]

admin if input.user.id in data.corax.config.admin.users

signed_in if employee

signed_in if admin

# Deliberately too broad: every employee may read the summary of every document. The policy allows
# it; the AI risk check denies the pairs that do not fit the access graph (as the profile route of
# PR #7's campus demo).
allow if {
	input.action == "read_summary"
	input.resource.type == "document"
	employee
	data.corax.graph[input.resource.id]
}

# Everyone signed in sees their profile, the catalog (only what they may open, titles, no content),
# the list of units and their own requests.
allow if {
	input.action in {"profile.read", "documents.list", "access.list_own", "units.list"}
	signed_in
}

# An employee may ask for access to a document (by its link) or to a whole unit: whether to grant it
# is the admin's call. The routes have no :id, so the AI check does not judge the asking.
allow if {
	input.action == "access.request"
	input.resource.type in {"access_request", "unit_request"}
	employee
}

# Only the admins review access requests (and so start appeals in Corax).
allow if {
	input.action == "access.review"
	admin
}

# An employee reads the documents of the projects they work on.
allow if {
	input.action == "read"
	input.resource.type == "document"
	some project in data.corax.graph[input.user.id].works_on
	project in data.corax.graph[input.resource.id].belongs_to
}

# An employee reads the public documents of their own department.
allow if {
	input.action == "read"
	input.resource.type == "document"
	"classification_public" in data.corax.graph[input.resource.id].classified_as
	some department in data.corax.graph[input.user.id].works_in
	department in data.corax.graph[input.resource.id].owned_by
}
