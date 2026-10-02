# Demo script

What to say while `scripts/demo.sh` runs. It has nine steps and takes about two minutes. For each step you get
the command (copied from the script), what the interviewer sees, what to say, and the follow-up it invites.

Terms are in [glossary.md](glossary.md). If a follow-up goes deep, the long answers are in
[qa_bank.md](qa_bank.md) and [failure_scenarios.md](failure_scenarios.md). The drawing to make before or after
the demo is in [whiteboard.md](whiteboard.md).

## Before you start

- Run it once the day before, on the laptop you will use: `./scripts/demo.sh`.
- It needs `uv`, `curl` and `jq`, port 8000 free, and network access for step 7 (it calls the live
  meta.discourse.org forum).
- It deletes and recreates `demo.db`, so every run starts clean.
- Every command is printed with a leading `$` before it runs, so the interviewer sees exactly what is called.
- The script stops at the first failure (`set -euo pipefail` and `curl --fail-with-body`), so a run that reaches
  `done` means every step passed.
- If there is no network: step 7 fails and the script stops. Say so, then run
  `uv run pytest tests/e2e/test_pull_to_query.py -q`, which runs the same pull against recorded Discourse
  responses.

Shell variables you will see: `$BASE` is `http://127.0.0.1:8000`, `$FIX` is `tests/fixtures`, `$PY` is
`.venv/bin/python`. `ACME_KEY` and `GLOBEX_KEY` are the two tenants' API keys, read from `.seed.json`.

---

## The 60-second opening

Say this before you press enter.

> "This is a feedback ingestion service. Feedback comes from four places: Playstore reviews, tweets, Intercom
> conversations and Discourse forum posts. Some sources push to us with signed webhooks; Discourse we pull on a
> timer. Many customers, called tenants, share the service, and each one only ever sees its own data.
>
> The design fits in one sentence: we save the raw payload to disk before we say yes, and everything after that
> is a retry or a replay. A webhook checks the API key, the source and the signature, writes one row to a
> `raw_events` table, and answers 202. A background worker takes rows from that table, asks the right connector
> to turn each one into a standard feedback record, and saves it keyed on source plus the source's own id. So
> duplicates collapse to one row, bad payloads go to a dead list, and anything can be replayed.
>
> This script runs that whole story against a real server and a real SQLite file. Watch for four things: a
> duplicate that is stored once, two apps of the same type, a tenant that sees nothing, and a `kill -9` that
> loses nothing."

---

## Step 1. Start the server

**Command:**
```
uv sync --quiet
rm -f demo.db demo.db-wal demo.db-shm
"$PY" -m uvicorn feedback_ingest.main:app --port "$PORT" >>"$TMP/server.log" 2>&1 &
curl -sS --fail-with-body "$BASE/health"
```

**They see:**
```
{"status":"ok","worker_enabled":true,"worker_alive":true,"scheduler_enabled":true,"scheduler_alive":true,
 "queue":{"pending":0,"processing":0,"processed":0,"failed":0,"dead":0}}
```

**Say:** "One process: the API, a worker thread and a pull scheduler thread. Health is the first thing I look at
in an incident: are both threads alive, and how deep is the queue."

**Follow-up:** "What makes health go red?"
**Answer:** A dead worker or scheduler thread, or no completed worker pass in about 10 seconds, gives 503
(`feedback_ingest/api/health.py`).

## Step 2. Seed two tenants and their sources

**Command:**
```
"$PY" scripts/seed.py
```

**They see:** one line per tenant (`acme`, `globex`) with its id and API key, then five sources each: a Discourse
`pull` source and four `push` sources (`android`, `ios-wrapper`, `twitter`, `intercom`) with their ids and
webhook secrets. Last line: `wrote .seed.json`.

**Say:** "A source is one tenant's configured connection. Acme has two Playstore apps, so that is two source
rows, each with its own secret. The API key and the secret are shown once, at creation; we store only a hash of
the key."

**Follow-up:** "Why is the Discourse source pull and the others push?"
**Answer:** Discourse has a public API we poll live; Playstore has no review webhook in reality, so recorded
fixtures stand in for that poller, and the transform is the same either way (ADR-003 context table).

## Step 3. The same review to acme-android twice

**Command:** (the script's `push` helper signs the file with `scripts/sign.py`, then runs)
```
curl -sS --fail-with-body -X POST "$BASE/v1/sources/$1/events" -H "X-API-Key: $ACME_KEY" \
  -H "X-Signature: $sig" --data-binary "@$3"
```
with `$1 = $ANDROID`, `$3 = tests/fixtures/playstore/review.json`, run twice.

**They see:**
```
{"raw_event_id":"<32 hex chars>","duplicate":false}
{"raw_event_id":null,"duplicate":true}
```

**Say:** "202 means saved, not processed yet. The second copy has the same event id, the review id plus its
last-modified time, so it is dropped, and we still answer 202 so the sender stops retrying."

**Follow-up:** "What if the signature is wrong?"
**Answer:** 401 and nothing is stored; the HMAC is checked on the raw bytes before we parse or write
(`feedback_ingest/api/ingest.py`).

## Step 4. The same review to acme-ios-wrapper

**Command:**
```
curl -sS --fail-with-body -X POST "$BASE/v1/sources/$IOS/events" -H "X-API-Key: $ACME_KEY" \
  -H "X-Signature: $sig" --data-binary "@tests/fixtures/playstore/review.json"
```
then the script waits until the queue is idle.

**They see:** `{"raw_event_id":"<32 hex chars>","duplicate":false}`.

**Say:** "Same payload, different source. It is not a duplicate, because both keys include the source id. Two
apps can share a review id without colliding."

**Follow-up:** "What if a tenant deletes the source and adds it again?"
**Answer:** Sources are disabled, never deleted (`PATCH` with `enabled: false`), so the old row and its keys stay;
a disabled source refuses pushes with 409.

## Step 5. Acme sees two records; globex sees none

**Command:**
```
curl -sS --fail-with-body "$BASE/v1/records?kind=review" -H "X-API-Key: $ACME_KEY" |
  jq -c '[.[] | {source_id, external_id}]'
curl -sS --fail-with-body "$BASE/v1/records?kind=review" -H "X-API-Key: $GLOBEX_KEY" | jq length
```

**They see:**
```
[{"source_id":"<android id>","external_id":"gp:AOqpTEST-review-0001"},
 {"source_id":"<ios id>","external_id":"gp:AOqpTEST-review-0001"}]
0
```

**Say:** "Three pushes, two records: the duplicate collapsed, and the second app is its own record with the same
external id. Globex runs the same query and gets zero, because every read is filtered by the tenant from the
API key."

**Follow-up:** "What if globex asks for acme's record by id?"
**Answer:** 404, not 403, so we do not even confirm it exists (`feedback_ingest/api/records.py`,
`tests/api/test_records_api.py`).

## Step 6. A malformed payload goes dead; replay runs it again

**Command:**
```
curl -sS --fail-with-body -X POST "$BASE/v1/sources/$ANDROID/events" -H "X-API-Key: $ACME_KEY" \
  -H "X-Signature: $sig" --data-binary "@tests/fixtures/playstore/malformed.json"
curl -sS --fail-with-body "$BASE/admin/raw-events?status=dead" -H "X-API-Key: $ACME_KEY" |
  jq -c '[.[] | {id, status, attempts, next_attempt_at}]'
curl -sS --fail-with-body -X POST "$BASE/admin/raw-events/$DEAD_ID/replay" -H "X-API-Key: $ACME_KEY"
curl -sS --fail-with-body "$BASE/admin/raw-events/$DEAD_ID" -H "X-API-Key: $ACME_KEY" |
  jq -c '{status, attempts, next_attempt_at, error: .error[:60]}'
```

**They see:** the push gets 202. The dead list has one row with `"status":"dead","attempts":1`. Replay answers
`{"status":"pending"}`. After the worker runs, the event is `dead` again with `attempts` 1 and an error that
starts `comments.0.userComment.lastModified: Field required`.

**Say:** "The payload is missing its timestamp and rating, so its input model rejects it. That is permanent, so
it goes dead on the first try, with the field name and no customer text. Replay puts it back to pending and
resets attempts; it dies again because the payload really is bad. That proves replay re-runs the stored
payload. After a real connector fix, the same call brings it back."

**Follow-up:** "What about a flaky failure, like a locked database?"
**Answer:** It retries with backoff (2, 4, 8, 16 seconds) and goes dead after 5 attempts
(`feedback_ingest/services/pipeline.py`, `tests/api/test_admin_api.py`).

## Step 7. Live Discourse pull

**Command:**
```
curl -sS --fail-with-body -X POST "$BASE/v1/sources/$FORUM/sync" -H "X-API-Key: $ACME_KEY"
curl -sS --fail-with-body "$BASE/v1/records?kind=post&limit=3" -H "X-API-Key: $ACME_KEY" |
  jq -c '[.[] | {external_id, title, author}]'
```

**They see:** a sync result like
`{"source_id":"<forum id>","pages":<n>,"accepted":<n>,"duplicates":0,"cursor":"2021-01-05T00:00:00","error":null}`, then three
real forum posts with their topic titles and authors.

**Say:** "Polling is just another producer. The connector fetches pages from the real forum, and every payload
goes through the same accept call as a webhook. The bookmark, the cursor, is saved only after the page's rows
are on disk. The seed fixes the window to four days in January 2021, so the demo is repeatable."

**Follow-up:** "What if Discourse rate-limits us halfway?"
**Answer:** The 429 becomes a transient error, the pull stops, saved pages stay saved, and the cursor has not
moved, so the next run starts from the same place and repeats are dropped (`feedback_ingest/services/pull.py`).

## Step 8. 20 pushes queued, kill -9, restart

**Command:**
```
FI_WORKER_ENABLED=false start_server
# 20 signed pushes of review.json, each with reviewId gp:demo-backlog-01 .. 20
curl -sS --fail-with-body "$BASE/admin/queue" -H "X-API-Key: $ACME_KEY"
kill -9 "$SERVER_PID"
start_server
curl -sS --fail-with-body "$BASE/admin/queue" -H "X-API-Key: $ACME_KEY"
```

**They see:** before the kill, the queue shows `"pending":20`. After the restart, "queue as it drains" prints the
counts three times, ending with `"pending":0` and `processed` up by 20.

**Say:** "I restart with the worker off, so the backlog is certainly there. Twenty webhooks get 202 and sit as
pending rows. Then `kill -9`: no shutdown, no flush. The new process finds the rows on disk and drains them. The
202 meant 'on disk', and that is why nothing is lost. It usually drains before the first print, which is the
point: the backlog was never in memory."

**Follow-up:** "What if it had been killed in the middle of an event?"
**Answer:** That row stays `processing` with a 30-second lease; when the lease runs out it is claimed again, and
the upsert makes the second run safe (`feedback_ingest/adapters/sqlalchemy/raw_event_queue.py`).

## Step 9. Stop the server

**Command:** the script's `stop_server` (a plain `kill` of the uvicorn process), then `echo "done"`.

**They see:** `done`. The trap on exit also deletes the temp folder with the server log and backlog files.

**Say:** "Every step ran against a real server and a real database file, and the script stops at the first
failure, so reaching 'done' means every claim I just made held."

**Follow-up:** "How do I know this is not a scripted fake?"
**Answer:** Open `tests/e2e/`: the same flows run as tests against a real SQLite file and the real worker
thread, and `uv run pytest` runs them all.

---

## The 30-second close

> "So, the four things: a duplicate stored once, two apps of the same type kept apart, a tenant that sees nothing
> of another, and a hard kill that lost nothing. Plus a bad payload parked with its reason and replayed, and a
> live pull through the same pipeline. All of it rests on one rule: save the raw payload before we say yes, then
> everything is a retry or a replay. Adding a new source is one connector file, one metadata model, one registry
> line and fixtures. Happy to add a field live, or to break something and show you where it lands."
