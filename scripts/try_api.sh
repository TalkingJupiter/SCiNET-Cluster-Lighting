#!/usr/bin/env bash
# Try every endpoint of a running rack-lighting API and report PASS/FAIL.
#
#   scripts/try_api.sh                 test Rack3 on http://127.0.0.1:8000
#   scripts/try_api.sh Rack5           test another rack
#   BASE=http://10.0.0.2:8000 scripts/try_api.sh
#
# Start the server first, in another terminal:
#   .venv/bin/uvicorn rack_lighting.api:create_app --factory --host 127.0.0.1 --port 8000
#
# This drives the REAL racks: the highlight lights U1, U21 and U42 on the
# chosen rack for hold-seconds, and a 35 kW reading is pushed for it (only
# visible in meter mode). Nothing else is changed. The power token is read
# from .env and never printed.

set -u

BASE=${BASE:-http://127.0.0.1:8000}
RACK=${1:-Rack3}
cd "$(dirname "$0")/.." || exit 2

pass=0
fail=0
BODY=$(mktemp)
trap 'rm -f "$BODY"' EXIT

green() { printf '\033[32m%s\033[0m' "$1"; }
red() { printf '\033[31m%s\033[0m' "$1"; }

# request METHOD PATH [curl args...] -> sets CODE, response body in $BODY
request() {
    local method=$1 path=$2
    shift 2
    CODE=$(curl -s -m 10 -o "$BODY" -w '%{http_code}' -X "$method" "$BASE$path" "$@")
}

# check NAME EXPECTED_CODES   (EXPECTED_CODES like "200" or "200|503")
check() {
    local name=$1 expected=$2
    if [[ "|$expected|" == *"|$CODE|"* ]]; then
        printf '  %s  %-48s %s\n' "$(green PASS)" "$name" "$CODE"
        pass=$((pass + 1))
    else
        printf '  %s  %-48s got %s, expected %s\n' "$(red FAIL)" "$name" "$CODE" "$expected"
        printf '        %s\n' "$(head -c 300 "$BODY")"
        fail=$((fail + 1))
    fi
}

# check_json NAME PYTHON_EXPR   (expr on `d`, the parsed body; must be true)
check_json() {
    local name=$1 expr=$2
    if python3 -c "import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if ($expr) else 1)" "$BODY" 2>/dev/null; then
        printf '  %s  %s\n' "$(green PASS)" "$name"
        pass=$((pass + 1))
    else
        printf '  %s  %s\n' "$(red FAIL)" "$name"
        printf '        %s\n' "$(head -c 300 "$BODY")"
        fail=$((fail + 1))
    fi
}

json() { curl_args=(-H 'Content-Type: application/json' -d "$1"); }

echo "API: $BASE    rack: $RACK"
echo

# ------------------------------------------------------------------ up?
echo "Health"
request GET /health
if [[ $CODE == 000 ]]; then
    echo "  $(red FAIL)  nothing answers at $BASE. Is the server running?"
    echo "        .venv/bin/uvicorn rack_lighting.api:create_app --factory --host 127.0.0.1 --port 8000"
    exit 2
fi
check "GET /health" 200
check_json "  says ok" 'd == {"status": "ok"}'

# ------------------------------------------------------------------ status
echo
echo "Status"
request GET /status
check "GET /status (200 ok/degraded, 503 down)" "200|503"
python3 - "$BODY" <<'EOF' 2>/dev/null || echo "        (could not read the status body)"
import json, sys
d = json.load(open(sys.argv[1]))
print(f"        overall: {d['status']}   mode: {d['mode']}")
for ip, c in d["controllers"].items():
    if c["reachable"]:
        note = f"LEDs {c['led_count']} (config {c['expected_led_count']})"
        if c["led_count_mismatch"]:
            note += "  <- mismatch"
        print(f"        {ip:16} up    {note}   WLED {c['wled_version']}")
    else:
        print(f"        {ip:16} DOWN  {c['last_error']}")
EOF

request GET /racks
check "GET /racks" 200
check_json "  lists $RACK" "'$RACK' in d"
if ! python3 -c "import json,sys; sys.exit(0 if '$RACK' in json.load(open(sys.argv[1])) else 1)" "$BODY" 2>/dev/null; then
    echo
    echo "$(red "Unknown rack $RACK"); pick one from GET /racks."
    exit 2
fi

# ------------------------------------------------------------------ highlight
echo
echo "Highlight (look at $RACK: U1, U21 and U42 on both sides)"
json '{"units": [1, 21, 42]}'
request POST "/racks/$RACK/highlight" "${curl_args[@]}"
check "POST /racks/$RACK/highlight [1, 21, 42]" 200
check_json "  echoes the units" 'd["units"] == [1, 21, 42]'
request GET /racks
check_json "  GET /racks shows it highlighted" "d['$RACK']['showing'] == [1, 21, 42]"

json '{"units": [1]}'
request POST /racks/NoSuchRack/highlight "${curl_args[@]}"
check "unknown rack" 404
json '{"units": [99]}'
request POST "/racks/$RACK/highlight" "${curl_args[@]}"
check "U99 (outside the rack)" 422
json '{"units": []}'
request POST "/racks/$RACK/highlight" "${curl_args[@]}"
check "no units" 422
json '{"units": [1, 3, 5, 7, 9]}'
request POST "/racks/$RACK/highlight" "${curl_args[@]}"
check "5 separate groups (over the segment budget)" 422

# ------------------------------------------------------------------ power
echo
echo "Power"
# Read .env with python-dotenv, exactly as the server does (it strips quotes).
TOKEN=$(.venv/bin/python -c "from dotenv import dotenv_values; print(dotenv_values('.env').get('power_ingest_token') or '')" 2>/dev/null)
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
READING="{\"kw\": 35, \"measured_at\": \"$NOW\"}"

if [[ -z $TOKEN ]]; then
    echo "  SKIP  no power_ingest_token in .env; push checks skipped"
else
    json "$READING"
    request PUT "/racks/$RACK/power" "${curl_args[@]}" -H "Authorization: Bearer $TOKEN"
    check "PUT 35 kW with the token" 204
    request GET "/racks/$RACK/power"
    check "GET /racks/$RACK/power" 200
    check_json "  reads back 35 kW" 'd["kw"] == 35 and d["age_seconds"] is not None'
fi

json "$READING"
request PUT "/racks/$RACK/power" "${curl_args[@]}" -H "Authorization: Bearer wrong-token"
check "PUT with a wrong token" 401
request PUT "/racks/$RACK/power" "${curl_args[@]}"
check "PUT with no token" 401
if [[ -n $TOKEN ]]; then
    json "{\"kw\": -5, \"measured_at\": \"$NOW\"}"
    request PUT "/racks/$RACK/power" "${curl_args[@]}" -H "Authorization: Bearer $TOKEN"
    check "PUT negative kW" 422
    json "$READING"
    request PUT /racks/NoSuchRack/power "${curl_args[@]}" -H "Authorization: Bearer $TOKEN"
    check "PUT for an unknown rack" 404
fi

# ------------------------------------------------------------------ result
echo
if [[ $fail -eq 0 ]]; then
    echo "$(green "All $pass checks passed.")"
else
    echo "$(red "$fail failed"), $pass passed."
fi
[[ $fail -eq 0 ]]
