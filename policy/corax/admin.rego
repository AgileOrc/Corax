# Admin API of ai-corax: the appeal endpoints (POST /appeals, /appeals/:id/pick, ...).
#
# Their routes are configured like any other route (config.routes), with one of admin_actions as
# the action. Such a request is allowed only for the users listed in config.admins; the
# application's rules, generated rules and exceptions are never asked (authz.rego), and there is
# no AI check: the resource is an appeal, not a node of the graph.
package corax.authz

admin_actions := {"submit_appeal", "read_appeal", "pick_candidate", "confirm_appeal", "reject_appeal"}

admin_route if request.action in admin_actions

admin_allow if {
	admin_route
	request.user.id in object.get(config, "admins", [])
}

allow if admin_allow
