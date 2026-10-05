#!/usr/bin/env bash
# Rehearsal against a local server in ~2 minutes (needs uv, curl, jq, openssl). Each command is echoed before it
# runs; each step ends with what changed in the counts.
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

step 1 "Start the server" "fresh demo.db; the worker and scheduler threads start with the app"
uv sync --quiet
rm -f demo.db demo.db-wal demo.db-shm
start_server
show curl -sS --fail-with-body "$BASE/health" | json
ok "status ok, worker and scheduler alive, empty queue"

step 2 "Seed two tenants and their sources" "lumenote (Play Store x2, Discourse, survey webhook), brightwave (Intercom, Twitter)"
show "$PY" scripts/seed.py
LUMENOTE_KEY="$(jq -r .lumenote.api_key .seed.json)" BRIGHTWAVE_KEY="$(jq -r .brightwave.api_key .seed.json)"
src() { jq -r ".lumenote.sources[\"lumenote-$1\"].$2" .seed.json; }
ANDROID="$(src android id)" ANDROID_SECRET="$(src android webhook_secret)"
BETA="$(src android-beta id)" BETA_SECRET="$(src android-beta webhook_secret)"
SURVEYS="$(src surveys id)" SURVEYS_SECRET="$(src surveys webhook_secret)" FORUM="$(src community id)"
ok "API keys and webhook secrets written to .seed.json (git-ignored)"

step 3 "Same review pushed twice" "idempotency: the second delivery hits UNIQUE(source_id, external_event_id)"
BEFORE="$(snap)"
push "$ANDROID" "$ANDROID_SECRET" "$FIX/playstore/review.json"
push "$ANDROID" "$ANDROID_SECRET" "$FIX/playstore/review.json"
wait_idle
note "2 pushes, 1 raw event: same raw_event_id, duplicate=false then true, both answered 202"
delta "$BEFORE"

step 4 "Same review to a second Play Store app" "multiple sources of one type: the record key is (source_id, external_id)"
BEFORE="$(snap)"
push "$BETA" "$BETA_SECRET" "$FIX/playstore/review.json"
wait_idle
delta "$BEFORE"

step 5 "Tenant isolation" "lumenote sees its 2 review records; brightwave, with its own key, sees 0"
show curl -sS --fail-with-body "$BASE/v1/records?kind=review" -H "X-API-Key: $LUMENOTE_KEY" |
  json '[.[] | {source_id, external_id, rating, language, metadata}]'
show curl -sS --fail-with-body "$BASE/v1/records?kind=review" -H "X-API-Key: $BRIGHTWAVE_KEY" | json length
note "same external_id, two source_ids: two records. brightwave: 0"

step 6 "Custom webhook: one batch, three records" "Enterpret's public record shape; each entry's type picks the kind"
BEFORE="$(snap)"
push "$SURVEYS" "$SURVEYS_SECRET" "$FIX/custom/batch.json"
wait_idle
show curl -sS --fail-with-body "$BASE/v1/records?source_id=$SURVEYS" -H "X-API-Key: $LUMENOTE_KEY" |
  json '[.[] | {external_id, kind}]'
show curl -sS --fail-with-body "$BASE/v1/records?kind=survey" -H "X-API-Key: $LUMENOTE_KEY" | json '.[].metadata'
note "1 raw event in, 3 records out"
delta "$BEFORE"

step 7 "Intercom and Twitter" "different source JSON, one uniform record shape; source-specific fields in metadata"
BEFORE="$(snap)"
bw() { jq -r ".brightwave.sources[\"brightwave-$1\"].$2" .seed.json; }
push "$(bw support id)" "$(bw support webhook_secret)" "$FIX/intercom/conversation.json"
push "$(bw x id)" "$(bw x webhook_secret)" "$FIX/twitter/tweet.json"
QUEUE_KEY="$BRIGHTWAVE_KEY" wait_idle
show curl -sS --fail-with-body "$BASE/v1/records" -H "X-API-Key: $BRIGHTWAVE_KEY" |
  json '.[] | {source_type, kind, language, author, metadata}'
delta "$BEFORE"

step 8 "Malformed payload: dead, then replayed" "stored anyway (202); dead on the first try; replay re-runs it"
BEFORE="$(snap)"
push "$ANDROID" "$ANDROID_SECRET" "$FIX/playstore/malformed.json"
wait_idle
show curl -sS --fail-with-body "$BASE/admin/raw-events?status=dead" -H "X-API-Key: $LUMENOTE_KEY" |
  json '[.[] | {id, status, attempts, error: .error[:70]}]'
note "dead after 1 attempt; the error names fields only, never customer text"
DEAD_ID="$(curl -sS --fail-with-body "$BASE/admin/raw-events?status=dead" -H "X-API-Key: $LUMENOTE_KEY" | jq -r '.[0].id')"
[ "$DEAD_ID" != null ] || { echo "no dead raw event to replay" >&2; exit 1; }
show curl -sS --fail-with-body -X POST "$BASE/admin/raw-events/$DEAD_ID/replay" -H "X-API-Key: $LUMENOTE_KEY" | json
wait_idle
show curl -sS --fail-with-body "$BASE/admin/raw-events/$DEAD_ID" -H "X-API-Key: $LUMENOTE_KEY" |
  json '{status, attempts, next_attempt_at, error: .error[:60]}'
note "dead again: the connector was not fixed. Real flow: fix, bump connector_version, deploy, replay"
delta "$BEFORE"

step 9 "Live Discourse pull" "meta.discourse.org, 2021-01-01 .. 2021-01-05; pulled posts go through the same accept as webhooks"
BEFORE="$(snap)"
SYNC="$(show curl -sS -X POST "$BASE/v1/sources/$FORUM/sync" -H "X-API-Key: $LUMENOTE_KEY")"
echo "$SYNC" | json
echo "$SYNC" | jq -e 'has("pages") and .error == null' >/dev/null || { echo "sync failed" >&2; exit 1; }
wait_idle
show curl -sS --fail-with-body "$BASE/v1/records?kind=post&limit=3" -H "X-API-Key: $LUMENOTE_KEY" |
  json '[.[] | {external_id, title, author}]'
note "the cursor moved to the window end; the next sync reads the next window"
delta "$BEFORE"

step 10 "Crash with a backlog: kill -9, restart, drain" "durable before ack: 20 accepted events survive a hard kill"
stop_server
FI_WORKER_ENABLED=false start_server  # worker off so the backlog is certain to be there
BEFORE="$(snap)"
for i in $(seq -w 1 20); do
  jq --arg id "gp:demo-backlog-$i" '.reviewId = $id' "$FIX/playstore/review.json" >"$TMP/r$i.json"
  push "$ANDROID" "$ANDROID_SECRET" "$TMP/r$i.json" >/dev/null 2>&1
done
show curl -sS --fail-with-body "$BASE/admin/queue" -H "X-API-Key: $LUMENOTE_KEY" | json
note "20 pending, nothing processed yet (worker off)"
show kill -9 "$SERVER_PID"; wait "$SERVER_PID" 2>/dev/null || true
start_server
note "restarted with the worker on; it claims the 20 leftover rows"
wait_idle
show curl -sS --fail-with-body "$BASE/admin/queue" -H "X-API-Key: $LUMENOTE_KEY" | json
delta "$BEFORE"
ok "all 20 processed after the kill: nothing accepted was lost"

step 11 "Stop the server"
stop_server
printf '\n%s%s  ✔ demo complete: every step passed%s\n\n' "$GRN" "$B" "$R"
