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

test_every_employee_reads_every_summary if {
	summary := object.union(read("ana", "doc_finance"), {"action": "read_summary"})
	authz.allow with input as summary with data.corax.graph as graph
	not authz.allow with input as object.union(summary, {"resource": {"type": "document", "id": "missing"}})
		with data.corax.graph as graph
	not authz.allow with input as object.union(summary, {"user": {"id": "nobody"}}) with data.corax.graph as graph
}

config := {"admin": {"users": ["root"]}}

request(user, action, type) := {"user": {"id": user}, "action": action, "resource": {"type": type}}

test_signed_in_users_see_profile_catalog_and_own_requests if {
	every action in ["profile.read", "documents.list", "access.list_own"] {
		authz.allow with input as request("ana", action, "x") with data.corax.graph as graph
		authz.allow with input as request("root", action, "x")
			with data.corax.graph as graph
			with data.corax.config as config
	}
}

test_strangers_see_nothing if {
	not authz.allow with input as request("nobody", "documents.list", "catalog")
		with data.corax.graph as graph
		with data.corax.config as config
}

test_employees_ask_for_access_to_any_document if {
	ask := {"user": {"id": "ana"}, "action": "access.request", "resource": {"type": "access_request", "document": "doc_finance"}}
	authz.allow with input as ask with data.corax.graph as graph
	not authz.allow with input as object.union(ask, {"user": {"id": "root"}})
		with data.corax.graph as graph
		with data.corax.config as config
}

test_only_admins_review_requests if {
	authz.allow with input as request("root", "access.review", "access_request")
		with data.corax.graph as graph
		with data.corax.config as config
	not authz.allow with input as request("ana", "access.review", "access_request")
		with data.corax.graph as graph
		with data.corax.config as config
}

ask(user, action, type) := {"user": {"id": user}, "action": action, "resource": {"type": type}}

test_employees_list_units_and_ask_for_a_unit if {
	authz.allow with input as ask("ana", "units.list", "unit") with data.corax.graph as graph
	authz.allow with input as ask("ana", "access.request", "unit_request") with data.corax.graph as graph
}

test_unit_requests_are_reviewed_by_admins_only if {
	not authz.allow with input as ask("ana", "access.review", "unit_request") with data.corax.graph as graph
	authz.allow with input as ask("admin_01", "access.review", "unit_request")
		with data.corax.graph as graph
		with data.corax.config.admin.users as ["admin_01"]
}
