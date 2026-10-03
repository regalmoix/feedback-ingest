# Firefight runbook

Two runbooks for live incidents. Each step has one command and tells you what a good result and a bad result look like. Work top to bottom and stop at the first step that shows the cause.

Before you start:
- The server runs at `http://127.0.0.1:8000`. Replace the placeholders once, then copy the commands as they are.
- `API_KEY` is the client's tenant key. Every tenant route under `/admin/raw-events`, `/admin/queue` and `/v1` takes it in the `X-API-Key` header and is scoped to that tenant, so you only ever see this client's data.
- Three routes take no API key. `/health` covers all tenants. The webhook `POST /v1/sources/{id}/events` uses the source id to pick the source and its HMAC signature to prove the sender. `POST /admin/tenants` takes the `X-Bootstrap-Token` header instead.
- Everything in this runbook is built and on `main`.
- Words like lease, dead letter, replay and cursor are in `docs/interview/glossary.md`. `docs/interview/failure_scenarios.md` explains each failure in more depth.

```
export API_KEY='<tenant api key>' SOURCE_ID='<source id>' EVENT_ID='<raw event id>'
```

---

## Runbook 1: "Our Playstore reviews have been missing since yesterday"

First, one thing to keep in mind. Playstore is a **push** source here: the client's side posts each review to `POST /v1/sources/{source_id}/events`. In this project fixture files stand in for that sender. (Enterpret's help center describes its Google Play connector as a pull every 4 hours. Ours is push, so there is no poll to check.) A review that is missing was lost in one of three places:
1. It never reached us, or we refused it (401, 404, 409, 400, 413 or 503 at the door).
2. We saved it, but the worker has not finished it (pending, failed or dead).
3. It was processed, but the client is looking in the wrong place (another source, or the wrong date filter).

### Step 1. Is the service alive?

```
curl -s -w '\nHTTP %{http_code}\n' http://127.0.0.1:8000/health
```

| Good | Bad, and what it means |
|---|---|
| `HTTP 200`, `"status": "ok"`, `"worker_alive": true`, `"scheduler_alive": true`, and small `pending` and `failed` numbers. The `queue` counts here cover all tenants. | `HTTP 503` with `"status": "degraded"`: the worker thread is dead (`"worker_alive": false`), or it has not finished a pass in about 10 seconds, or the scheduler thread is dead (`"scheduler_enabled": true` with `"scheduler_alive": false`). Only these threads change the status code. A dead scheduler alone does not explain missing Playstore reviews, because Playstore is push. Restart the server either way. Saved work drains from disk, and in-flight rows come back after the 30-second lease. |
| | `HTTP 503` with `"detail": "storage unavailable"`: the database is down. Every webhook is getting 503 too. The sender should retry, so fix the database first. |
| | No reply at all: the server is down. Every delivery since then has failed at the sender's end. |

`failing_sources` is a count of pull sources whose last scheduled sync failed. It never makes health red, and it has no ids. It does not matter for a push source like Playstore.

### Step 2. What does this client's queue look like?

```
curl -s http://127.0.0.1:8000/admin/queue -H "X-API-Key: $API_KEY"
```

| Good | Bad, and what it means |
|---|---|
| `pending`, `processing` and `failed` are 0 or small. `dead` has not grown since yesterday. | `pending` is large and not shrinking: the worker is stuck or slow. Go back to step 1. |
| | `failed` above 0: something flaky, like a database lock. These retry on their own, 4 times, with a wait of 2, 4, 8, then 16 seconds. Read their `error` in step 3, using `status=failed`. |
| | `dead` has grown: go to step 3. |
| | Every count looks normal, and `processed` has not grown since yesterday: the reviews never reached us. Go to step 5, checks C, D and E. |

401 here means the API key is wrong. Get the right key before going further.

### Step 3. List the dead events for this source

```
curl -s "http://127.0.0.1:8000/admin/raw-events?status=dead&limit=500" -H "X-API-Key: $API_KEY" | jq --arg s "$SOURCE_ID" '[.[] | select(.source_id == $s) | {id, attempts, error, received_at}]'
```

The list route has no source filter, so `jq` does the filtering. It comes back newest first, with at most 500 rows.

| Good | Bad, and what it means |
|---|---|
| `[]`: nothing for this source is dead. | Many rows since yesterday, all with the same error, like `reviewId: Field required`: the sender changed its payload shape, or our transform has a bug. Go to step 5, check B. |
| | `review has no user comment`: the payload holds only a developer reply, or no comment at all. That goes dead on purpose, so a bad payload does not look like "no data". Look at one in step 4. |
| | Errors like `OperationalError (see logs)` or `TransientError: …` after `attempts: 5`: a flaky cause that outlasted the retries. An unexpected error is stored only as its type plus `(see logs)`; the details are in the server log under its `raw_event_id`. If that cause is gone now, go to step 5, check A. |
| | `attempt limit exceeded`: the event was claimed more than 5 times without finishing. That happens when the process dies while working on it, for example a crash or an out-of-memory kill, instead of a normal error. Read the server log for its `raw_event_id` before you replay it, or it may do the same again. |
| | `source not found`: the source row is gone or belongs to someone else. Escalate. |

### Step 4. Look at one raw event

Copy one `id` from step 3 into `EVENT_ID`.

```
curl -s "http://127.0.0.1:8000/admin/raw-events/$EVENT_ID" -H "X-API-Key: $API_KEY" | jq '{status, attempts, error, received_at, payload}'
```

| Good | Bad, and what it means |
|---|---|
| The payload has the same shape as `tests/fixtures/playstore/review.json`: `reviewId`, then `comments[0].userComment` with `text`, `lastModified.seconds` and `starRating`. | A field is renamed or missing: it is a schema change. Step 5, check B. |
| | `comments` holds only a `developerComment`: the transform drops developer replies, finds no user comment, and the event goes dead with `review has no user comment`. That is correct. Tell the client the sender posted a reply, not a review. |
| | `404` with `raw event … not found`: wrong id, or it belongs to another tenant. |

This shows the client's real review text. Do not paste it into tickets or chat.

### Step 5. Decide what to do

Match what you found to one row.

| You found | Do this |
|---|---|
| **A.** Dead events, and the cause is fixed now (the database is back, or a bug was patched). | Replay them. See step 6. |
| **B.** Dead events with a shape or validation error. | Fix the input model in `feedback_ingest/connectors/playstore.py`. Add the new payload as a fixture next to `tests/fixtures/playstore/review.json`. Bump `version` in the connector. Run `uv run pytest`. Restart the server. Then replay (step 6). |
| **C.** Nothing arrived: `processed` did not grow, and nothing is dead. | Read the server's access log for this source's URL. `401`: wrong signature (check E); the webhook takes no API key. `404`: wrong source id in the sender's URL. `409`: the source is disabled (check D), or it is a pull source, which never takes webhooks (`source does not accept webhooks`). `400`: the body is not a JSON object. `413`: the body is over 1 MiB. `503`: our database was down, and the sender should retry. Our own app logs do not record 401s, so the access log is the place to look. |
| **D.** Is the source there, and is it the one the client thinks? | Run the source check below. A disabled source refuses signed webhooks with 409 `source is disabled`, so `enabled: false` **does** explain missing Playstore reviews: everything sent while it was off was refused, not stored. Turn it back on (the `PATCH` command in Runbook 2, step 2) and ask the client to re-send that period. Repeats are safe. |
| **E.** The client says "we are sending" but you see 401s. | Run the signature probe below. It tells you whether the secret the client uses matches ours, and it stores nothing. |
| **F.** It is a pull source, not Playstore. | Run a manual sync, then see Runbook 2. For a push source like Playstore, sync answers 409 `source … is not an enabled pull source`. |

Access log lines for this source (use whatever file uvicorn writes to):

```
grep "/v1/sources/$SOURCE_ID/events" server.log | tail -20
```

Source check:

```
curl -s "http://127.0.0.1:8000/v1/sources/$SOURCE_ID" -H "X-API-Key: $API_KEY" | jq '{name, type, mode, enabled, cursor}'
```

Good: `type` is `playstore`, `mode` is `push`, and the `name` is the app the client means. A client with two Android apps has two sources, and their reviews are separate. Bad: `404` means this tenant does not own that source id.

Signature probe. The body `[]` is valid JSON but not an object, so a request with a correct signature gets 400 and nothing is written. `scripts/sign.py` only signs: it prints the hex HMAC of a file and sends nothing. It reads the secret from `FI_SIGN_SECRET`. Paste the secret the client says it uses at the silent prompt, so it stays out of your shell history:

```
read -rs FI_SIGN_SECRET && export FI_SIGN_SECRET && printf '[]' > probe.json && SIG=$(.venv/bin/python scripts/sign.py probe.json)
```

```
curl -s -w '\nHTTP %{http_code}\n' -X POST "http://127.0.0.1:8000/v1/sources/$SOURCE_ID/events" -H "X-Signature: $SIG" --data-binary @probe.json
```

Good: `HTTP 400` with `body must be a JSON object`, so the secret matches. `HTTP 409` with `source is disabled` also means the secret matches; the source is just off (check D). Bad: `HTTP 401` with `bad or missing signature`, so the client's secret is not ours. There is no rotation endpoint today, so either the client goes back to the secret it got when the source was created, or an operator updates `sources.webhook_secret` by hand.

### Step 6. Replay

One event:

```
curl -s -X POST "http://127.0.0.1:8000/admin/raw-events/$EVENT_ID/replay" -H "X-API-Key: $API_KEY"
```

Good: `{"status": "pending"}`. The worker picks it up within about a second. Bad: `409` with `event is being processed` means a worker holds a live lease on it right now, so wait and try again (once the lease expires, replay works even if the worker died). `404` means a wrong id.

Every dead event for this source, in one call:

```
curl -s -X POST "http://127.0.0.1:8000/admin/raw-events/replay?source_id=$SOURCE_ID&status=dead&limit=500" -H "X-API-Key: $API_KEY"
```

Good: `{"replayed": n}`, where `n` matches the dead count from step 3. It only touches this tenant's rows. It takes the newest 500 at most, so if `n` is 500, run it again: the rows already replayed are `pending` now, so the next call picks the next 500.

Replay is safe to repeat, because the upsert is keyed on `(source_id, external_id)` and goes through the same version check. If a bug made **wrong** records, not dead ones, replay the `processed` events too, with `status=processed`. Run that one only once per fix: replayed rows become `processed` again, so a second call would pick the same newest rows.

### Step 7. Check that it worked

```
curl -s "http://127.0.0.1:8000/v1/records?source_id=$SOURCE_ID&kind=review&since=<yesterday, e.g. 2026-10-02T00:00:00>&limit=500" -H "X-API-Key: $API_KEY" | jq 'length, (.[-1] | {external_id, source_created_at, ingested_at, connector_version})'
```

Good: the count matches what the client expects. The list is oldest first, so `.[-1]` is the newest of these. It has a recent `ingested_at`. After a fix, `connector_version` shows the new version. Run step 2 again: `pending` and `failed` are back to 0, and `dead` has not grown.

Bad: still 0. Be aware that `since` filters on the source's own time, not on when the review reached us. For Playstore that time is the comment's `lastModified`: when the review was last written or edited. A review last changed three days ago and delivered today does not match `since=yesterday`. Try again without `since` before you escalate.

### Step 8. Tell the client

Send the first message within 15 minutes, even if you do not know the cause yet. Send an update every hour until it is fixed.

| Field | What to write |
|---|---|
| Subject | Playstore reviews delayed for `<app name>`: `<investigating / fixed>` |
| What you saw | "Reviews from `<app name>` stopped appearing from `<first missing time, UTC>`." |
| What we found | "`<one plain sentence: e.g. the review format changed and our importer rejected the new format>`." |
| Data | "No reviews were lost. We keep every review we receive, and we have re-run them." Or, if they never reached us: "Reviews sent between `<start, UTC>` and `<end, UTC>` were refused. Please re-send them; repeats are safe and will not create duplicates." |
| Status now | "`<n>` reviews restored as of `<time, UTC>`." Or: "The fix is in progress; next update by `<time, UTC>`." |
| Next | "`<what we will do next, e.g. add an alert so we notice within minutes>`." |

Only say "no data was lost" if step 7 proves it.

### Step 9. Post-incident note

Write this within one working day. Keep it blameless: describe what happened, not who did it.

| Heading | What goes in it |
|---|---|
| Summary | One sentence: what broke, for whom, and for how long (start and end, UTC). |
| Timeline | Detected, client told, cause found, fixed, verified. One line each, with the time. |
| What broke | The technical cause, e.g. "the Playstore payload renamed `reviewId`; every event failed validation and went to the dead list". |
| Blast radius | Which tenants and sources, how many raw events, how many records were late or missing. Was any data lost? (Usually no, if it reached `raw_events`.) |
| Fix | What changed (connector file, version bump), and how many events were replayed. |
| Prevention | What would have caught it sooner: an alert on dead count per source, an alert on "no new records for N hours", a fixture from the new payload, a contract test. |
| Follow-ups | Each with an owner and a date. |

---

## Runbook 2: "Discourse pull stopped advancing"

Discourse is a **pull** source. The scheduler runs every enabled pull source once per tick, every `FI_PULL_INTERVAL_SECONDS` (default 300, that is 5 minutes). Enterpret's help center describes a 4-hour polling cadence for support tools and app stores, so a slower interval is a normal setting, not a hack. Each run reads the source's **cursor**, searches one window of `window_days` days (default 7) starting there, and moves the cursor **only on the final page** of that window. Five things can stop it moving:
- a **429** or other error part-way through,
- the **10-page cap**: a window holding more than about 500 posts never reaches its final page (Discourse refuses page 11, so we stop at 10). About 500 posts per day is the hard limit of Discourse search,
- the **pull deadline** (`FI_PULL_DEADLINE_SECONDS`, default 60) or the **reply size cap** (`FI_HTTP_MAX_BYTES`, default 2,000,000),
- a **bad config**,
- the scheduler itself is not running, or the source is disabled.

### Step 1. Is the scheduler running?

```
curl -s http://127.0.0.1:8000/health | jq '{status, scheduler_enabled, scheduler_alive, worker_alive, failing_sources}'
```

Good: `"scheduler_alive": true`. Bad: `"scheduler_alive": false` with `"scheduler_enabled": true` means the scheduler thread is gone. Health then answers 503 with `"status": "degraded"`. Restart the server. If `scheduler_enabled` is `false`, the scheduler was turned off on purpose (`FI_SCHEDULER_ENABLED=false`), so nothing pulls on its own and health does not count it. The first tick runs one interval after start, so use step 3 to sync now.

`failing_sources` above 0 means at least one pull source failed on the last scheduled tick. It is a count across all tenants, with no ids, and it does not change the status code. The log lines in step 4 name the source.

### Step 2. Where is the cursor, and is the source on?

```
curl -s "http://127.0.0.1:8000/v1/sources/$SOURCE_ID" -H "X-API-Key: $API_KEY" | jq '{enabled, cursor, config}'
```

| Good | Bad, and what it means |
|---|---|
| `enabled: true`, and `cursor` is close to now (within a day). | `enabled: false`: the scheduler skips disabled sources, and a manual sync gets 409. Turn it back on with the command below. |
| | `cursor` is days or weeks old: it is stuck. Go to step 3. |
| | `cursor` is `null`: no page has ever been saved. The next run starts from `config.start_after`. |
| | `cursor` equals `config.start_after`, or stays at the same old value run after run: the run saves pages but never reaches the final page. This is usually the 10-page cap. Step 3 shows it. |
| | `config.base_url` is wrong: every call fails. Step 3 shows the error. |

```
curl -s -X PATCH "http://127.0.0.1:8000/v1/sources/$SOURCE_ID" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{"enabled": true}'
```

### Step 3. Run one sync by hand and read the result

```
curl -s -w '\nHTTP %{http_code}\n' -X POST "http://127.0.0.1:8000/v1/sources/$SOURCE_ID/sync" -H "X-API-Key: $API_KEY"
```

The reply has `pages`, `accepted` (new), `duplicates`, `cursor` and `error`. Run it twice and compare the `cursor`. When `error` is set the reply is HTTP 502. `error` holds the status and the URL, like `429 from https://…/search.json`, never the reply body. A storage failure is not in `error`: the sync answers 503 `storage unavailable`. Any other bug of ours is a 500.

| What you see | What it means | What to do |
|---|---|---|
| `error: null`, `cursor` moved forward | Healthy. It was only behind. | Run it a few more times, or wait for the scheduler. Each run moves at most `window_days`. |
| `error: null`, `cursor` close to now, `accepted: 0` | Caught up, with no new posts. Some `duplicates` are normal, because of the 60-second overlap. | Nothing. Note that the pull searches by **creation** date, so an edit to an old post is not picked up. That is expected, not a stall. |
| `error` has `429` or `5xx`, or a timeout | Discourse is rate-limiting us or is down. The pages before the error are saved, but the cursor did not move. | Wait. The scheduler retries every tick and does not back off. If it keeps happening, raise `FI_PULL_INTERVAL_SECONDS` and restart. Check that only **one** process is pulling: under `uvicorn --workers N`, every process runs its own scheduler. |
| `error` says `window exceeds 10 pages; about 500 posts per day is the hard limit of Discourse search; lower window_days via PATCH`, `pages: 10`, `cursor` unchanged | The 10-page cap. The run stops after page 10 without reaching its final page, so the cursor does not move. Every run re-reads the same pages, and they all come back as duplicates. | Make the window smaller (command below). |
| `error` is `pull deadline exceeded` | The run used up `FI_PULL_DEADLINE_SECONDS` (60 by default). Pages before it are saved; the cursor did not move. | A smaller window makes each run shorter. If Discourse is just slow, raise `FI_PULL_DEADLINE_SECONDS` and restart. |
| `error` has `response too large from` | One reply was over `FI_HTTP_MAX_BYTES`. | Raise `FI_HTTP_MAX_BYTES` and restart, or shrink the window. |
| `error` has `301 from`, `302 from` or another 3xx | We do not follow redirects, so a moved forum stops here. | Point `base_url` at the final address (command below). |
| `error` is `discourse search reported an error` | Discourse answered with an error inside a normal reply. Its text is only in the WARNING log line, step 4. | Read that line. Usually a bad query or a forum setting. |
| `error` has `omitted posts` | Discourse search listed a post that the topic call did not return, often a post deleted a moment ago. It retries, and usually clears when Discourse's search catches up. | Wait a few ticks. If it stays stuck on the same topic, escalate. Moving the cursor past it by hand skips those posts. |
| `error` has `404 from` or another 4xx | The `base_url` is wrong, or the forum is private. | Fix `config.base_url` with the `PATCH` below. It is checked again: a plain http(s) URL, no user name or password, not an internal host. |
| HTTP `503` with `storage unavailable` | Our database failed during the run. Pages before the error are saved. | Fix the database first (Runbook 1, step 1), then sync again. |
| HTTP `409` with `is not an enabled pull source` | This is a push source, or a disabled pull source. | Push source: use Runbook 1. Disabled: turn it on (step 2). |
| HTTP `409` with `is already syncing` | Another sync of this source is running in this process, often the scheduler's. | Wait for it to finish, then run step 3 again. |

Shrink the window, or fix the URL. `PATCH` merges `config` key by key and checks the result again (422 if it is invalid). Values are strings, so write `"1"`, not `1`. `window_days` must be 1 to 31. The server reads sources fresh on every run, so no restart is needed:

```
curl -s -X PATCH "http://127.0.0.1:8000/v1/sources/$SOURCE_ID" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{"config": {"window_days": "1"}}'
```

```
curl -s -X PATCH "http://127.0.0.1:8000/v1/sources/$SOURCE_ID" -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" -d '{"config": {"base_url": "https://<forum host>"}}'
```

Set the cursor by hand. The API cannot change the cursor, so edit the database: the SQLite file in `FI_DATABASE_URL` (default `./feedback.db`). The format is an ISO date and time in UTC, with no timezone. Moving it **back** is always safe, because repeats are dropped. Moving it **forward** skips posts:

```
sqlite3 feedback.db "UPDATE sources SET cursor = '2026-10-01T00:00:00' WHERE id = '<source id>';"
```

### Step 4. Read the pull log lines for this source

```
grep "source_id=$SOURCE_ID" server.log | grep -E "pulled|pull stopped|discourse search error|skipped|abandoned" | tail -20
grep -A 40 -E "scheduled sync failed|scheduler tick failed" server.log | grep -E "^[A-Za-z_.]+(Error|Exception): " | tail -5
```

Good: `pulled N pages: X new, Y duplicates` once per tick. Bad: `pull stopped at the saved cursor: …` (a source error, like a 429, the deadline or the page cap) on every tick. `discourse search error: …` holds the text Discourse sent back. `skipped: a manual sync is running` is harmless. `sync abandoned at shutdown` means the server stopped mid-run; the next run resumes from the saved cursor. `scheduled sync failed` with a traceback is our own failure, such as the database; the tick moved on to the next source. `scheduler tick failed` means the tick could not even list the sources.

### Step 5. Check that records arrive

A moving cursor only means raw events were saved. The worker still has to turn them into records, so check both.

```
curl -s http://127.0.0.1:8000/admin/queue -H "X-API-Key: $API_KEY"
```

```
curl -s "http://127.0.0.1:8000/v1/records?source_id=$SOURCE_ID&kind=post&since=<cursor date from step 2>&limit=5" -H "X-API-Key: $API_KEY" | jq '[.[] | {external_id, title, source_created_at}]'
```

Good: `pending` drains to 0, and new posts appear. Bad: `dead` grows for this source. Go to Runbook 1, step 3, and treat it the same way. If other tenants' `pending` is huge too, one tenant's burst may be ahead of this one in the shared queue (see the noisy tenant row in `failure_scenarios.md`).

### Step 6. Tell the client, and write the note

Use the same templates as Runbook 1, steps 8 and 9. For a pull source the data line is usually: "No posts were lost. We read the forum again from where we stopped, and repeats are dropped." That is true because the cursor only moves after rows are saved. It stops being true if someone moved the cursor **forward** by hand, so say that if it happened.
