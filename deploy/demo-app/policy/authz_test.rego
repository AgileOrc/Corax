package app.authz_test

import data.app.authz

graph := {
	"ana": {"works_on": ["project_sales1"], "works_in": ["department_sales"]},
	"doc_project": {
		"belongs_to": ["project_sales1"],
		"owned_by": ["department_sales"],
		"classified_as": ["classification_confidential"],
	},
	"doc_public": {
		"belongs_to": ["project_sales2"],
		"owned_by": ["department_sales"],
		"classified_as": ["classification_public"],
	},
	"doc_internal": {
		"belongs_to": ["project_sales2"],
		"owned_by": ["department_sales"],
		"classified_as": ["classification_internal"],
	},
	"doc_finance": {
		"belongs_to": ["project_finance1"],
		"owned_by": ["department_finance"],
		"classified_as": ["classification_public"],
	},
}

read(user, document) := {"user": {"id": user}, "action": "read", "resource": {"type": "document", "id": document}}

test_reads_documents_of_own_projects if {
	authz.allow with input as read("ana", "doc_project") with data.corax.graph as graph
}

test_reads_public_documents_of_own_department if {
	authz.allow with input as read("ana", "doc_public") with data.corax.graph as graph
}

test_no_other_documents_of_own_department if {
	not authz.allow with input as read("ana", "doc_internal") with data.corax.graph as graph
}

test_no_public_documents_of_other_departments if {
	not authz.allow with input as read("ana", "doc_finance") with data.corax.graph as graph
}

test_only_reading if {
	not authz.allow with input as object.union(read("ana", "doc_project"), {"action": "delete"})
		with data.corax.graph as graph
}

test_unknown_user_or_document if {
	not authz.allow with input as read("nobody", "doc_project") with data.corax.graph as graph
	not authz.allow with input as read("ana", "missing") with data.corax.graph as graph
}
