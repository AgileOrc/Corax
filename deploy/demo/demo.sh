#!/usr/bin/env bash
# The Corax demo through Envoy, on the dummy campus. Run from the repository root after
#   docker compose -f deploy/docker-compose.yml up --build -d
# Reset between runs (removes the rules from appeals): docker compose -f deploy/docker-compose.yml down -v
#
# Needs only docker and curl: tokens are signed and JSON is read with the Python inside the service container.
# The ids are those of output/dummy trained as in docs/getting-started/quickstart.md; another model may
# give other risks, so check the pairs with scripts/similar_cases.py first.
set -euo pipefail

COMPOSE="docker compose -f deploy/docker-compose.yml"
URL="${CORAX_URL:-http://localhost:8080}"

LECTURER=lecturer_P1_0          # teaches students of P1
OTHER_STUDENT=student_P5_01     # a student of P5: no course, no advising
OWN_STUDENT=student_P1_00       # a student LECTURER teaches
HEAD=lecturer_head_P2           # head of program P2, never appeals
HEAD_STUDENT=student_P2_14      # a P2 student HEAD has no rule for (low AI risk)
APPELLANT=lecturer_head_P0      # head of program P0, appeals
APPEALED=student_P0_05
ADMIN=admin_rina

# Python of the service container: PyJWT and the demo config (/config/data.json) are there
py() { $COMPOSE exec -T service python -c "$1"; }

# A demo JWT for a user, signed like scripts/make_token.py with the secret of deploy/demo/data.json
token() {
	py "import json, time, jwt
c = json.load(open('/config/data.json'))['corax']['config']['jwt']
now = int(time.time())
print(jwt.encode({'sub': '$1', 'iss': c['iss'], 'aud': c['aud'], 'iat': now, 'exp': now + 600}, c['secret'], algorithm='HS256'))"
}

step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

# GET through Envoy as a user; prints the status code and Envoy's log line with OPA's reason and the AI risk
call() {
	local user=$1 path=$2 code
	code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $(token "$user")" "$URL$path")
	printf '%s GET %s -> %s\n' "$user" "$path" "$code"
	sleep 1
	$COMPOSE logs --no-log-prefix --since 10s envoy | grep -F "GET $path " | tail -1 | sed 's/^/   envoy: /' || true
}

json() { py "import json, sys; data = json.load(sys.stdin); print($1)"; }

step "1. BOLA: a lecturer asks for the grades of a student of another program -> policy denies"
call "$LECTURER" "/students/$OTHER_STUDENT/grades"

step "2. Over-broad rule: every lecturer may read every profile"
call "$LECTURER" "/students/$OWN_STUDENT/profile"
echo "   ... and a profile that does not fit the access graph -> policy allows, AI denies"
call "$LECTURER" "/students/$OTHER_STUDENT/profile"

step "3. A head of program has no rule for the students of their program yet"
call "$HEAD" "/students/$HEAD_STUDENT/grades"

step "4. An admin approves the appeal of another head of program ($APPELLANT -> $APPEALED)"
admin=$(token "$ADMIN")
created=$(curl -s -X POST "$URL/corax/appeals" -H "Authorization: Bearer $admin" -H "Content-Type: application/json" \
	-d "{\"user\": \"$APPELLANT\", \"object\": \"$APPEALED\", \"action\": \"read_grades\", \"reason\": \"head of program reviews grades\"}")
id=$(echo "$created" | json 'data["id"]')
echo "$created" | json '"\n".join("   #%(index)s %(users)3s users %(pairs)4s pairs  %(pattern)s" % c for c in data["candidates"][:4])'
pick=$(echo "$created" | json 'next(c["index"] for c in data["candidates"] if c["pattern"] == "user.member_of = object.member_of AND user holds position_head_of_program")')
echo "   $id: exception written; the admin picks #$pick"
curl -s -X POST "$URL/corax/appeals/$id/confirm" -H "Authorization: Bearer $admin" -H "Content-Type: application/json" \
	-d "{\"candidate\": $pick, \"acknowledge_scope\": false}" \
	| json '"   %(status)s, tier %(tier)s: %(users)s users, %(pairs)s pairs; validation ok: " % {**data, **data["chosen"]["scope"]} + ", ".join(c["name"] for c in data["validation"] if c["ok"])'

step "5. OPA picks up the new file (no restart)"
sleep 2
$COMPOSE exec -T service ls /policies/generated | sed 's/^/   generated: /'
$COMPOSE logs --no-log-prefix --since 30s opa | grep -i 'watch' | tail -2 | sed 's/^/   opa: /' || true

step "6. Step 3 again: the head of P2 never appealed, the rule from appeal $id now covers them"
call "$HEAD" "/students/$HEAD_STUDENT/grades"

step "7. Revoke: delete the rule file -> step 3 is denied again"
$COMPOSE exec -T service rm "/policies/generated/$id-rule.rego"
sleep 2
call "$HEAD" "/students/$HEAD_STUDENT/grades"
