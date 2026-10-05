# Helpers for scripts/demo.sh; sourced, not run. Expects BASE, PY, TMP and LUMENOTE_KEY;
# QUEUE_KEY=<key> wait_idle waits on another tenant's queue. NO_COLOR=1 or a pipe turns colour off.
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  B=$'\e[1m' DIM=$'\e[2m' RED=$'\e[31m' GRN=$'\e[32m' YEL=$'\e[33m' CYN=$'\e[36m' MAG=$'\e[35m' R=$'\e[0m'
  JQ=(jq -C)
else
  B="" DIM="" RED="" GRN="" YEL="" CYN="" MAG="" R="" JQ=(jq)
fi
RULE="$(printf '%.0s─' $(seq 78))"

show() {  # echo the command (keys and signatures shortened), then run it
  local arg out=""
  for arg in "$@"; do
    case "$arg" in
      X-API-Key:* | X-Signature:*) out+=" '${arg:0:24}...'" ;;
      *) out+=" $(printf '%q' "$arg")" ;;
    esac
  done
  printf '\n%s$%s%s\n' "$CYN" "$out" "$R" >&2
  "$@"
}
step() {  # step "N" "title" "why it matters"
  printf '\n\n%s%s%s\n%s  STEP %s  %s%s\n' "$MAG" "$RULE" "$R" "$B" "$1" "$2" "$R"
  [ -n "${3:-}" ] && printf '%s  %s%s\n' "$DIM" "$3" "$R"
  printf '%s%s%s\n' "$MAG" "$RULE" "$R"
}
note() { printf '%s  ▶ %s%s\n' "$YEL" "$*" "$R"; }
ok() { printf '%s  ✔ %s%s\n' "$GRN" "$*" "$R"; }
json() { "${JQ[@]}" -c "${@:-.}"; }

start_server() {  # python directly, not `uv run`, so kill -9 hits uvicorn itself
  if curl -fs "$BASE/health" >/dev/null; then echo "port $PORT is already serving" >&2; exit 1; fi
  "$PY" -m uvicorn feedback_ingest.main:app --port "$PORT" >>"$TMP/server.log" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 50); do
    kill -0 "$SERVER_PID" 2>/dev/null || break
    curl -fs "$BASE/health" >/dev/null && return; sleep 0.2
  done
  echo "server did not come up:" >&2; cat "$TMP/server.log" >&2; exit 1
}
stop_server() {
  if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" 2>/dev/null || true; fi
  wait "$SERVER_PID" 2>/dev/null || true
  SERVER_PID=""
}

push() {  # source_id secret file
  local sig; sig="$(FI_SIGN_SECRET="$2" "$PY" scripts/sign.py "$3")"
  show curl -sS --fail-with-body -X POST "$BASE/v1/sources/$1/events" -H "X-Signature: $sig" \
    --data-binary "@$3" | json
}
queue() { curl -sS --fail-with-body "$BASE/admin/queue" -H "X-API-Key: ${QUEUE_KEY:-$LUMENOTE_KEY}"; }
wait_idle() {
  for _ in $(seq 60); do
    [ "$(queue | jq '.pending + .processing + .failed')" = 0 ] && return; sleep 0.5
  done
  echo "queue did not drain" >&2; return 1
}

# Delta: snapshot raw-event counts and record counts per tenant, then print what changed.
records() { curl -sS --fail-with-body "$BASE/v1/records?limit=500" -H "X-API-Key: $1" | jq length; }
snap() {
  jq -n --argjson lq "$(QUEUE_KEY=$LUMENOTE_KEY queue)" --argjson lr "$(records "$LUMENOTE_KEY")" \
    --argjson bq "$(QUEUE_KEY=$BRIGHTWAVE_KEY queue)" --argjson br "$(records "$BRIGHTWAVE_KEY")" \
    '{lumenote: {raw_events: $lq, records: $lr}, brightwave: {raw_events: $bq, records: $br}}'
}
delta() {  # delta "$BEFORE": print every count that moved since that snapshot
  local line; printf '%s  Δ what changed%s\n' "$B" "$R"
  jq -rn --argjson a "$1" --argjson b "$(snap)" '
    [$b | paths(numbers)] | map(. as $p | {p: ($p | join(".")), d: (($b | getpath($p)) - (($a | getpath($p)) // 0))})
    | map(select(.d != 0)) | if length == 0 then "= (no change)" else .[] | "\(if .d > 0 then "+" else "" end)\(.d)  \(.p)" end' |
    while IFS= read -r line; do
      case "$line" in +*) printf '%s    %s%s\n' "$GRN" "$line" "$R" ;; -*) printf '%s    %s%s\n' "$RED" "$line" "$R" ;;
        *) printf '%s    %s%s\n' "$DIM" "$line" "$R" ;; esac
    done
}
