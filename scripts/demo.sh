#!/usr/bin/env bash
# Rehearsal: the whole story against a local server in ~2 minutes. Needs uv, curl, jq.
# Every command is echoed (to stderr) before it runs so it can be copied at the whiteboard.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
export FI_BASE_URL="http://127.0.0.1:$PORT" FI_DATABASE_URL="sqlite:///./demo.db"
export FI_WORKER_POLL_SECONDS=2
BASE="$FI_BASE_URL" FIX=tests/fixtures PY=.venv/bin/python
TMP="$(mktemp -d)" SERVER_PID=""

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
trap 'stop_server; rm -rf "$TMP"' EXIT

push() {  # source_id secret file
  local sig; sig="$("$PY" scripts/sign.py "$2" "$3")"
  show curl -sS --fail-with-body -X POST "$BASE/v1/sources/$1/events" -H "X-Signature: $sig" \
    --data-binary "@$3"
  echo
}
queue() { curl -sS --fail-with-body "$BASE/admin/queue" -H "X-API-Key: $ACME_KEY"; }
wait_idle() {
  for _ in $(seq 60); do
    [ "$(queue | jq '.pending + .processing + .failed')" = 0 ] && return; sleep 0.5
  done
  echo "queue did not drain" >&2; return 1
}

step "1. start the server"
uv sync --quiet
rm -f demo.db demo.db-wal demo.db-shm
start_server
show curl -sS --fail-with-body "$BASE/health"; echo

step "2. seed two tenants and their sources"
show "$PY" scripts/seed.py
ACME_KEY="$(jq -r .acme.api_key .seed.json)" GLOBEX_KEY="$(jq -r .globex.api_key .seed.json)"
src() { jq -r ".acme.sources[\"acme-$1\"].$2" .seed.json; }
ANDROID="$(src android id)" ANDROID_SECRET="$(src android webhook_secret)"
IOS="$(src ios-wrapper id)" IOS_SECRET="$(src ios-wrapper webhook_secret)" FORUM="$(src forum id)"

step "3. same review to acme-android twice: duplicate=false, then true"
push "$ANDROID" "$ANDROID_SECRET" "$FIX/playstore/review.json"
push "$ANDROID" "$ANDROID_SECRET" "$FIX/playstore/review.json"

step "4. same review to acme-ios-wrapper: a second source of the same type"
push "$IOS" "$IOS_SECRET" "$FIX/playstore/review.json"
wait_idle

step "5. acme sees 2 review records (same external_id, two sources); globex sees 0"
show curl -sS --fail-with-body "$BASE/v1/records?kind=review" -H "X-API-Key: $ACME_KEY" |
  jq -c '[.[] | {source_id, external_id}]'
show curl -sS --fail-with-body "$BASE/v1/records?kind=review" -H "X-API-Key: $GLOBEX_KEY" | jq length

step "6. malformed payload goes dead; replay runs it again and it goes dead again"
push "$ANDROID" "$ANDROID_SECRET" "$FIX/playstore/malformed.json"
wait_idle
show curl -sS --fail-with-body "$BASE/admin/raw-events?status=dead" -H "X-API-Key: $ACME_KEY" |
  jq -c '[.[] | {id, status, attempts, next_attempt_at}]'
DEAD_ID="$(curl -sS --fail-with-body "$BASE/admin/raw-events?status=dead" -H "X-API-Key: $ACME_KEY" | jq -r '.[0].id')"
[ "$DEAD_ID" != null ] || { echo "no dead raw event to replay" >&2; exit 1; }
show curl -sS --fail-with-body -X POST "$BASE/admin/raw-events/$DEAD_ID/replay" -H "X-API-Key: $ACME_KEY"; echo
wait_idle
show curl -sS --fail-with-body "$BASE/admin/raw-events/$DEAD_ID" -H "X-API-Key: $ACME_KEY" |
  jq -c '{status, attempts, next_attempt_at, error: .error[:60]}'

step "7. live Discourse pull (meta.discourse.org, 2021-01-01 .. 2021-01-05)"
SYNC="$(show curl -sS --fail-with-body -X POST "$BASE/v1/sources/$FORUM/sync" -H "X-API-Key: $ACME_KEY")"
echo "$SYNC" | jq -c .
echo "$SYNC" | jq -e '.error == null' >/dev/null || { echo "sync failed" >&2; exit 1; }
wait_idle
show curl -sS --fail-with-body "$BASE/v1/records?kind=post&limit=3" -H "X-API-Key: $ACME_KEY" |
  jq -c '[.[] | {external_id, title, author}]'

step "8. 20 pushes queued, kill -9, restart: the backlog drains"
stop_server
FI_WORKER_ENABLED=false start_server  # worker off so the backlog is certain to be there
for i in $(seq -w 1 20); do
  jq --arg id "gp:demo-backlog-$i" '.reviewId = $id' "$FIX/playstore/review.json" >"$TMP/r$i.json"
  push "$ANDROID" "$ANDROID_SECRET" "$TMP/r$i.json" >/dev/null
done
show curl -sS --fail-with-body "$BASE/admin/queue" -H "X-API-Key: $ACME_KEY"; echo
show kill -9 "$SERVER_PID"
wait "$SERVER_PID" 2>/dev/null || true
start_server
echo "restarted; queue as it drains:"
for _ in 1 2 3; do queue; echo; sleep 1; done
wait_idle
show curl -sS --fail-with-body "$BASE/admin/queue" -H "X-API-Key: $ACME_KEY"; echo

step "9. stop the server"
stop_server
echo "done"
