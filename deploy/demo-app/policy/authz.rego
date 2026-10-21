# Rules of the demo application (the document store), written by people. scripts/make_enterprise.py
# records exactly what they allow as the access history.
#
# The input is the normalised request of policy/corax/request.rego; relations come from the graph
# that hgnn-job exports (data.corax.graph). Rules added through appeals live in app.generated and
# app.exceptions, never in this package.
package app.authz

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
