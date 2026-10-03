#!/usr/bin/env bash
# Rehearsal: the whole story against a local server in ~2 minutes. Needs uv, curl, jq, openssl.
# Every command is echoed (to stderr) before it runs so it can be copied at the whiteboard.
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
export FI_BASE_URL="http://127.0.0.1:$PORT" FI_DATABASE_URL="sqlite:///./demo.db"
export FI_WORKER_POLL_SECONDS=2
export FI_BOOTSTRAP_TOKEN="$(openssl rand -hex 32)"  # the default token is refused
BASE="$FI_BASE_URL" FIX=tests/fixtures PY=.venv/bin/python
TMP="$(mktemp -d)" SERVER_PID=""

source scripts/demo_lib.sh
trap 'stop_server; rm -rf "$TMP"' EXIT

step "1. start the server"
uv sync --quiet
rm -f demo.db demo.db-wal demo.db-shm
start_server
show curl -sS --fail-with-body "$BASE/health"; echo

step "2. seed two tenants and their sources"
show "$PY" scripts/seed.py
LUMENOTE_KEY="$(jq -r .lumenote.api_key .seed.json)" BRIGHTWAVE_KEY="$(jq -r .brightwave.api_key .seed.json)"
src() { jq -r ".lumenote.sources[\"lumenote-$1\"].$2" .seed.json; }
ANDROID="$(src android id)" ANDROID_SECRET="$(src android webhook_secret)"
BETA="$(src android-beta id)" BETA_SECRET="$(src android-beta webhook_secret)"
SURVEYS="$(src surveys id)" SURVEYS_SECRET="$(src surveys webhook_secret)" FORUM="$(src community id)"

step "3. same review to lumenote-android twice: duplicate=false, then true"
push "$ANDROID" "$ANDROID_SECRET" "$FIX/playstore/review.json"
push "$ANDROID" "$ANDROID_SECRET" "$FIX/playstore/review.json"

step "4. same review to lumenote-android-beta: a second source of the same type"
push "$BETA" "$BETA_SECRET" "$FIX/playstore/review.json"
wait_idle

step "5. lumenote sees 2 review records (same external_id, two sources); brightwave sees 0"
show curl -sS --fail-with-body "$BASE/v1/records?kind=review" -H "X-API-Key: $LUMENOTE_KEY" |
  jq -c '[.[] | {source_id, external_id, rating, language, metadata}]'
show curl -sS --fail-with-body "$BASE/v1/records?kind=review" -H "X-API-Key: $BRIGHTWAVE_KEY" | jq length

step "6. custom webhook (Enterpret's public record shape): one batch, three records, three kinds"
push "$SURVEYS" "$SURVEYS_SECRET" "$FIX/custom/batch.json"
wait_idle
show curl -sS --fail-with-body "$BASE/v1/records?source_id=$SURVEYS" -H "X-API-Key: $LUMENOTE_KEY" |
  jq -c '[.[] | {external_id, kind}]'
show curl -sS --fail-with-body "$BASE/v1/records?kind=survey" -H "X-API-Key: $LUMENOTE_KEY" | jq -c '.[].metadata'

step "7. brightwave's Intercom and Twitter sources: one uniform record shape"
bw() { jq -r ".brightwave.sources[\"brightwave-$1\"].$2" .seed.json; }
push "$(bw support id)" "$(bw support webhook_secret)" "$FIX/intercom/conversation.json"
push "$(bw x id)" "$(bw x webhook_secret)" "$FIX/twitter/tweet.json"
QUEUE_KEY="$BRIGHTWAVE_KEY" wait_idle
show curl -sS --fail-with-body "$BASE/v1/records" -H "X-API-Key: $BRIGHTWAVE_KEY" |
  jq -c '.[] | {source_type, kind, language, author, metadata}'

step "8. malformed payload goes dead; replay runs it again and it goes dead again"
push "$ANDROID" "$ANDROID_SECRET" "$FIX/playstore/malformed.json"
wait_idle
show curl -sS --fail-with-body "$BASE/admin/raw-events?status=dead" -H "X-API-Key: $LUMENOTE_KEY" |
  jq -c '[.[] | {id, status, attempts, next_attempt_at}]'
DEAD_ID="$(curl -sS --fail-with-body "$BASE/admin/raw-events?status=dead" -H "X-API-Key: $LUMENOTE_KEY" | jq -r '.[0].id')"
[ "$DEAD_ID" != null ] || { echo "no dead raw event to replay" >&2; exit 1; }
show curl -sS --fail-with-body -X POST "$BASE/admin/raw-events/$DEAD_ID/replay" -H "X-API-Key: $LUMENOTE_KEY"; echo
wait_idle
show curl -sS --fail-with-body "$BASE/admin/raw-events/$DEAD_ID" -H "X-API-Key: $LUMENOTE_KEY" |
  jq -c '{status, attempts, next_attempt_at, error: .error[:60]}'

step "9. live Discourse pull (meta.discourse.org, 2021-01-01 .. 2021-01-05)"
SYNC="$(show curl -sS --fail-with-body -X POST "$BASE/v1/sources/$FORUM/sync" -H "X-API-Key: $LUMENOTE_KEY")"
echo "$SYNC" | jq -c .
echo "$SYNC" | jq -e '.error == null' >/dev/null || { echo "sync failed" >&2; exit 1; }
wait_idle
show curl -sS --fail-with-body "$BASE/v1/records?kind=post&limit=3" -H "X-API-Key: $LUMENOTE_KEY" |
  jq -c '[.[] | {external_id, title, author}]'

step "10. 20 pushes queued, kill -9, restart: the backlog drains"
stop_server
FI_WORKER_ENABLED=false start_server  # worker off so the backlog is certain to be there
for i in $(seq -w 1 20); do
  jq --arg id "gp:demo-backlog-$i" '.reviewId = $id' "$FIX/playstore/review.json" >"$TMP/r$i.json"
  push "$ANDROID" "$ANDROID_SECRET" "$TMP/r$i.json" >/dev/null
done
show curl -sS --fail-with-body "$BASE/admin/queue" -H "X-API-Key: $LUMENOTE_KEY"; echo
show kill -9 "$SERVER_PID"
wait "$SERVER_PID" 2>/dev/null || true
start_server
echo "restarted; queue as it drains:"
for _ in 1 2 3; do queue; echo; sleep 1; done
wait_idle
show curl -sS --fail-with-body "$BASE/admin/queue" -H "X-API-Key: $LUMENOTE_KEY"; echo

step "11. stop the server"
stop_server
echo "done"
