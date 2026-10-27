# Turns the Envoy ext_authz input into the request the application's rules see:
#
#   {
#     "user":     {"id": "<sub from the verified JWT>"},
#     "action":   "<action of the matched route>",
#     "resource": {"type": "<resource_type of the route>", "<param>": "<value from the URL path>", ...}
#   }
#
# Identity comes only from a verified JWT and the resource only from the URL path.
# The request body and query string are never used.
package corax.authz

config := data.corax.config

http_request := input.attributes.request.http

# --- JWT ----------------------------------------------------------------

token := t if {
	auth := http_request.headers.authorization
	startswith(auth, "Bearer ")
	t := substring(auth, 7, -1)
}

# config.jwt holds the io.jwt.decode_verify constraints: "secret" (HS256) or "cert" (JWKS / PEM),
# and optionally "iss" and "aud". Expiry ("exp", "nbf") is checked against the current time.
claims := payload if {
	[valid, _, payload] := io.jwt.decode_verify(token, config.jwt)
	valid
}

user_id := claims.sub if is_string(claims.sub)

# --- Route --------------------------------------------------------------

# "/students/ani/grades/IF201?x=1" -> ["students", "ani", "grades", "IF201"]
path_segments := split(trim(split(http_request.path, "?")[0], "/"), "/")

# A route path like "/students/:id/grades/:course_code"; ":name" matches one non-empty segment.
segment_matches(pattern, segment) if {
	startswith(pattern, ":")
	segment != ""
}

segment_matches(pattern, segment) if {
	not startswith(pattern, ":")
	pattern == segment
}

route_matches(path) if {
	pattern := split(trim(path, "/"), "/")
	count(pattern) == count(path_segments)
	every i, p in pattern {
		segment_matches(p, path_segments[i])
	}
}

# Corax's own admin routes (served by corax-service); applications do not list them in config.routes.
corax_routes := [
	{"method": "POST", "path": "/corax/appeals", "action": "corax.appeal.create", "resource_type": "appeal"},
	{"method": "GET", "path": "/corax/appeals/:id", "action": "corax.appeal.read", "resource_type": "appeal"},
	{"method": "GET", "path": "/corax/appeals/:id/candidates/:candidate", "action": "corax.appeal.read", "resource_type": "appeal"},
	{"method": "POST", "path": "/corax/appeals/:id/confirm", "action": "corax.appeal.confirm", "resource_type": "appeal"},
	{"method": "POST", "path": "/corax/appeals/:id/revoke", "action": "corax.appeal.revoke", "resource_type": "appeal"},
	{"method": "GET", "path": "/corax/rules", "action": "corax.rules.read", "resource_type": "rules"},
	{"method": "GET", "path": "/corax/me/access", "action": "corax.me.access", "resource_type": "access"},
]

matched_routes contains r if {
	some r in array.concat(object.get(config, "routes", []), corax_routes)
	r.method == http_request.method
	route_matches(r.path)
}

# Exactly one route must match; an ambiguous request is denied.
route := r if {
	count(matched_routes) == 1
	some r in matched_routes
}

params[name] := path_segments[i] if {
	some i, p in split(trim(route.path, "/"), "/")
	startswith(p, ":")
	name := substring(p, 1, -1)
}

# --- Normalised request ---------------------------------------------------

request := {
	"user": {"id": user_id},
	"action": route.action,
	"resource": object.union(params, {"type": route.resource_type}),
}
