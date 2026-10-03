# Helpers for scripts/demo.sh; sourced, not run. Expects BASE, PY, TMP and LUMENOTE_KEY;
# QUEUE_KEY=<key> wait_idle waits on another tenant's queue.
show() { printf '\n$' >&2; printf ' %q' "$@" >&2; printf '\n' >&2; "$@"; }
step() { printf '\n=== %s\n' "$*"; }

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
    --data-binary "@$3"
  echo
}
queue() { curl -sS --fail-with-body "$BASE/admin/queue" -H "X-API-Key: ${QUEUE_KEY:-$LUMENOTE_KEY}"; }
wait_idle() {
  for _ in $(seq 60); do
    [ "$(queue | jq '.pending + .processing + .failed')" = 0 ] && return; sleep 0.5
  done
  echo "queue did not drain" >&2; return 1
}
