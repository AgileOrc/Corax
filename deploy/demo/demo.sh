#!/usr/bin/env bash
# The Corax demo through Envoy, on the dummy campus. Run from the repository root after
#   docker compose -f deploy/docker-compose.yml up --build -d
# It starts from no appeals; to run it again, reset first: docker compose -f deploy/docker-compose.yml down -v
#
#   A. denied by policy                 the policy alone decides
#   B. allowed by policy, checked by Corax   the AI risk check lets a fitting pair through and denies an odd one
#   C. appeals                          small rule (applied at once), large rule declined by the admin,
#                                       large rule approved by the admin, revoke
#   D. what the admin sees              every rule in effect, who gained access and how it was used
#
# Needs only docker and curl: tokens are signed and JSON is read with the Python inside the service container.
# The ids are those of output/dummy trained as in docs/getting-started.md; another model may
# give other risks, so check the pairs with scripts/similar_cases.py first.
set -euo pipefail

COMPOSE="docker compose -f deploy/docker-compose.yml"
URL="${CORAX_URL:-http://localhost:8080}"
ADMIN=admin_rina

# A and B
LECTURER=lecturer_P1_0             # teaches students of P1
OWN_STUDENT=student_P1_00          # a student LECTURER teaches
OTHER_STUDENT=student_P5_01        # a student of P5: no course, no advising
# C, small: a head of program appeals; another head of program is covered without appealing
SMALL_APPELLANT=lecturer_head_P0
SMALL_APPEALED=student_P0_05
SMALL_OTHER=lecturer_head_P2
SMALL_OTHER_STUDENT=student_P2_14  # low AI risk for SMALL_OTHER
# C, large and declined
DECLINED_APPELLANT=lecturer_P3_1
DECLINED_APPEALED=student_P3_06
DECLINED_OTHER_STUDENT=student_P3_12
# C, large and approved, then revoked
APPROVED_APPELLANT=lecturer_P4_1
APPROVED_APPEALED=student_P4_07
APPROVED_OTHER=lecturer_P4_2
APPROVED_OTHER_STUDENT=student_P4_09
# the patterns the admin picks
HEAD_OF_PROGRAM="user.member_of = object.member_of AND user holds position_head_of_program"
SAME_PROGRAM="user.member_of = object.member_of"

# --- helpers ----------------------------------------------------------------------------

# Python of the service container: PyJWT, the demo config (/config/data.json) and the service code are there
py() { $COMPOSE exec -T service python -c "$1"; }

# a demo JWT for a user, signed like scripts/make_token.py with the secret of deploy/demo/data.json
token() {
	py "import json, time, jwt
c = json.load(open('/config/data.json'))['corax']['config']['jwt']
now = int(time.time())
print(jwt.encode({'sub': '$1', 'iss': c['iss'], 'aud': c['aud'], 'iat': now, 'exp': now + 600}, c['secret'], algorithm='HS256'))"
}

# evaluates a Python expression over the JSON read from stdin (as `data`)
json() { py "import json, sys; data = json.load(sys.stdin); print($1)"; }

section() {
	printf '\n============================================================\n'
	printf ' \033[1m%s\033[0m\n' "$1"
	printf '============================================================\n'
}

case_title() { printf '\n\033[1mCase %s\033[0m\n' "$1"; }

status_text() {
	case $1 in
		200) echo "200 OK" ;; 201) echo "201 Created" ;; 403) echo "403 Forbidden" ;;
		409) echo "409 Conflict" ;; 422) echo "422 Unprocessable" ;; *) echo "$1" ;;
	esac
}

# GET through Envoy as a user; sets CODE, REASON and RISK (from Envoy's access log: OPA's reason, AI risk)
request() {
	local user=$1 path=$2 line
	CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $(token "$user")" "$URL$path")
	sleep 1
	line=$($COMPOSE logs --no-log-prefix --since 15s envoy | grep -F "GET $path " | tail -1 || true)
	REASON=$(echo "$line" | sed -n 's/.* reason=\(.*\) risk=.*/\1/p')
	RISK=$(echo "$line" | sed -n 's/.* risk=\(.*\)$/\1/p')
}

# "0.9999984952700969" -> "1.0000"; "-" when the AI was not asked
risk_text() { [ -z "$1" ] || [ "$1" = "-" ] && echo "-" || printf '%.4f' "$1"; }

# one line: GET <path> as <user> -> <status> (<reason>)
check() {
	request "$1" "$2"
	printf '  %-8s: GET %s as %s -> %s (%s' "$3" "$2" "$1" "$CODE" "$REASON"
	[ "$(risk_text "$RISK")" = "-" ] && printf ')\n' || printf ', risk %s)\n' "$(risk_text "$RISK")"
}

# POST to the Corax admin API; sets CODE and BODY
admin_post() {
	local response
	response=$(curl -s -w '\n%{http_code}' -X POST "$URL$1" -H "Authorization: Bearer $ADMIN_TOKEN" \
		-H "Content-Type: application/json" -d "$2")
	CODE=$(echo "$response" | tail -1)
	BODY=$(echo "$response" | sed '$d')
}

# GET through Envoy with a token; prints the body
get_as() { curl -s -H "Authorization: Bearer $1" "$URL$2"; }

create_appeal() {
	admin_post /corax/appeals "{\"user\": \"$1\", \"object\": \"$2\", \"action\": \"read_grades\", \"reason\": \"$3\"}"
	APPEAL=$(echo "$BODY" | json "data['id']")
	PICK=$(echo "$BODY" | json "next(c['index'] for c in data['candidates'] if c['pattern'] == '$4')")
	printf '  request : POST /corax/appeals -> %s, %s, exception written\n' "$(status_text "$CODE")" "$APPEAL"
	printf '  admin   : accepts candidate #%s: %s\n' "$PICK" \
		"$(echo "$BODY" | json "data['candidates'][$PICK - 1]['description']")"
}

confirm() {
	admin_post "/corax/appeals/$APPEAL/confirm" "$1"
	printf '  request : POST /corax/appeals/%s/confirm %s\n' "$APPEAL" "$1"
	printf '  response: %s' "$(status_text "$CODE")"
	if [ "$CODE" = 409 ]; then echo ", needs admin confirmation"; else echo ", $(echo "$BODY" | json "data['status']")"; fi
}

# What the admin reads, in plain language: who would gain access (from a 409), who gained access and
# how it was used (from GET /corax/rules)
VIEW=$(cat <<'PY'
import json, sys
data = json.load(sys.stdin)
part = sys.argv[1]

def people(access, indent="              "):
    for u in access["by_user"][:5]:
        print(f"{indent}{u['user']}: {', '.join(u['objects'])}")
    more = access["users"] - min(len(access["by_user"]), 5)
    if more > 0:
        print(f"{indent}and {more} more")

if part == "would":
    a = data["affected"]
    print(f"  would give access to {a['users']} people, {a['objects']} students:")
    people(a)
    sys.exit()

entries = [e for e in data if part == "all" or (e["appeal"] == sys.argv[2] and e["kind"] == sys.argv[3])]
for e in entries:
    lines = e["summary"]
    used = next(i for i, line in enumerate(lines) if line.startswith(("Used", "Not used")))
    if part == "granted":
        print(f"  access  : {lines[2]}")
        people(e["access"])
    elif part == "usage":
        for line in lines[used:]:
            print(f"  usage   : {line.strip()}")
    else:
        print(f"\n  {e['appeal']} ({e['kind']})")
        for line in lines[:used]:
            print(f"    {line}")
        for line in lines[used:]:
            print(f"    {line.strip()}" if not line.startswith("  ") else f"      {line.strip()}")
PY
)
view() { $COMPOSE exec -T service python -c "$VIEW" "$@"; }
rules() { get_as "$ADMIN_TOKEN" /corax/rules; }

# the resources a user can reach through appeals, as that user sees them
my_access() {
	printf '  user    : GET /corax/me/access as %s -> %s\n' "$1" \
		"$(get_as "$(token "$1")" /corax/me/access | json "', '.join(data['resources']) or 'nothing'")"
}

# the three tier indicators of a scope, against the limits the service runs with
INDICATORS=$(cat <<'PY'
import json, sys
from config import Settings
limits = Settings.from_env().tier_limits
data = json.load(sys.stdin)
s = data["scope"] if "scope" in data else data["chosen"]["scope"]
risk = s["mean_risk"]
rows = [
    ("users affected", f"{s['users']} ({s['user_share']:.0%})", f"{limits.max_user_share:.0%}", s["user_share"] <= limits.max_user_share),
    ("new pairs", str(s["pairs"]), str(limits.max_pairs), s["pairs"] <= limits.max_pairs),
    ("mean risk", "-" if risk is None else f"{risk:.2f}", f"{limits.max_mean_risk:.2f}", risk is None or risk <= limits.max_mean_risk),
]
print("  indicators" + " " * 8 + f"{'value':>10}{'limit':>8}")
for name, value, limit, ok in rows:
    print(f"    {name:16}{value:>10}{limit:>8}    {'ok' if ok else 'over'}")
tier = s["tier"].upper()
print(f"  tier    : {tier} -> " + ("applied without a second confirmation" if tier == "SMALL" else "waiting for the admin"))
PY
)
indicators() {
	echo "$BODY" | $COMPOSE exec -T service python -c "$INDICATORS"
	[ "$CODE" != 409 ] || echo "$BODY" | view would
}

# who gained access when the rule was written; the Rego file itself is only named
show_access() {
	printf '  policy  : + %s (enforced by OPA)\n' "$1-rule.rego"
	rules | view granted "$1" rule
}

# how long OPA took to load the change, from its "Processed file watch event" log line
opa_reloaded() {
	local line
	sleep 2
	line=$($COMPOSE logs --no-log-prefix --since "$1" opa | grep 'Processed file watch event' | tail -1 || true)
	if [ -n "$line" ]; then
		printf '  opa     : reloaded in %s ms (no restart)\n' "$(echo "$line" | sed -n 's/.*"duration":\([0-9]*\).*/\1/p' | awk '{printf "%.0f", $1 / 1000000}')"
	else
		echo "  opa     : no watch event in the log yet"
	fi
}

now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# --- demo -------------------------------------------------------------------------------

if [ -n "$($COMPOSE exec -T service ls /policies/generated)" ]; then
	echo "Rules from an earlier run are still loaded. Reset first: $COMPOSE down -v && $COMPOSE up -d" >&2
	exit 1
fi
THRESHOLD=$(py "import json, urllib.request; print('%.3f' % json.load(urllib.request.urlopen('http://localhost:8000/health'))['risk_threshold'])")
ADMIN_TOKEN=$(token "$ADMIN")

section "A. Denied by policy"

case_title "1: $LECTURER requests access to $OTHER_STUDENT"
request "$LECTURER" "/students/$OTHER_STUDENT/grades"
printf '  request : GET /students/%s/grades\n  response: %s\n  reason  : %s\n' "$OTHER_STUDENT" "$(status_text "$CODE")" "$REASON"

section "B. Allowed by policy, checked by Corax"

case_title "2: $LECTURER requests access to $OWN_STUDENT"
request "$LECTURER" "/students/$OWN_STUDENT/profile"
printf '  request : GET /students/%s/profile\n  response: %s\n  threshold = %s, risk = %s\n  reason  : %s\n' \
	"$OWN_STUDENT" "$(status_text "$CODE")" "$THRESHOLD" "$(risk_text "$RISK")" "$REASON"

case_title "3: $LECTURER requests access to $OTHER_STUDENT"
request "$LECTURER" "/students/$OTHER_STUDENT/profile"
printf '  request : GET /students/%s/profile\n  response: %s\n  threshold = %s, risk = %s\n  reason  : %s\n' \
	"$OTHER_STUDENT" "$(status_text "$CODE")" "$THRESHOLD" "$(risk_text "$RISK")" "$REASON"

section "C. Appeals"

case_title "4 (small): $SMALL_APPELLANT appeals to access $SMALL_APPEALED, then the admin accepts"
check "$SMALL_OTHER" "/students/$SMALL_OTHER_STUDENT/grades" before
create_appeal "$SMALL_APPELLANT" "$SMALL_APPEALED" "head of program reviews grades" "$HEAD_OF_PROGRAM"
since=$(now)
confirm "{\"candidate\": $PICK}"
indicators
show_access "$APPEAL"
opa_reloaded "$since"
check "$SMALL_OTHER" "/students/$SMALL_OTHER_STUDENT/grades" after
rules | view usage "$APPEAL" rule
my_access "$SMALL_OTHER"

case_title "5 (large, admin declines): $DECLINED_APPELLANT appeals to access $DECLINED_APPEALED"
create_appeal "$DECLINED_APPELLANT" "$DECLINED_APPEALED" "needs one student's grades" "$SAME_PROGRAM"
confirm "{\"candidate\": $PICK}"
indicators
echo "  admin   : declines the rule, keeps only the exception"
confirm '{"candidate": null}'
printf '  policy  : + %s-exception.rego (only %s -> %s)\n' "$APPEAL" "$DECLINED_APPELLANT" "$DECLINED_APPEALED"
check "$DECLINED_APPELLANT" "/students/$DECLINED_OTHER_STUDENT/grades" after

case_title "6 (large, admin approves): $APPROVED_APPELLANT appeals to access $APPROVED_APPEALED"
check "$APPROVED_OTHER" "/students/$APPROVED_OTHER_STUDENT/grades" before
create_appeal "$APPROVED_APPELLANT" "$APPROVED_APPEALED" "lecturers read grades in their program" "$SAME_PROGRAM"
confirm "{\"candidate\": $PICK}"
indicators
echo "  admin   : approves after reviewing the scope"
since=$(now)
confirm "{\"candidate\": $PICK, \"acknowledge_scope\": true}"
show_access "$APPEAL"
opa_reloaded "$since"
check "$APPROVED_OTHER" "/students/$APPROVED_OTHER_STUDENT/grades" after
rules | view usage "$APPEAL" rule
REVOKE=$APPEAL

case_title "7: revoke the rule of case 6"
since=$(now)
admin_post "/corax/appeals/$REVOKE/revoke" '{}'
printf '  request : POST /corax/appeals/%s/revoke -> %s, %s\n' "$REVOKE" "$(status_text "$CODE")" \
	"$(echo "$BODY" | json "data['status']")"
printf '  policy  : - %s-rule.rego (deleted, revoke recorded)\n' "$REVOKE"
opa_reloaded "$since"
check "$APPROVED_OTHER" "/students/$APPROVED_OTHER_STUDENT/grades" after
my_access "$APPROVED_OTHER"

section "D. What the admin sees"

echo "  GET /corax/rules: every rule and exception from an appeal that is still in effect"
rules | view all
