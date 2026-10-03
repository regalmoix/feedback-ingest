import logging
from collections import defaultdict
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from functools import partial
from itertools import batched
from typing import Any

from pydantic import BaseModel, ValidationError

from feedback_ingest.connectors.base import PullPage
from feedback_ingest.connectors.discourse_models import SearchHitIn, SearchPageIn, TopicPostsIn
from feedback_ingest.domain.errors import PermanentError, TransientError
from feedback_ingest.domain.models import Source
from feedback_ingest.ports.clock import Clock
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.utils.html import strip_tags
from feedback_ingest.utils.time import NAIVE_UTC

log = logging.getLogger(__name__)
_OVERLAP = timedelta(seconds=60)
_MAX_PAGES = 10  # Discourse answers 400 for page > 10
_POSTS_PER_CALL = 20


# ponytail: every poll re-scans the whole window; store last post id per topic if Discourse
# volume grows. The cursor only advances on the final page because search order is not
# guaranteed oldest-first; a crash mid-run re-fetches from the old cursor (dedup absorbs it).
# ponytail: at most 10 search pages (~500 posts) per window, so about 500 posts per day is the hard
# limit; a busier window raises after page 10 with the cursor unmoved. Page by date past that.
def pull_pages(
    source: Source, http: HttpClient, clock: Clock, deadline: datetime
) -> Iterator[PullPage]:
    check = partial(_check_deadline, clock, deadline)
    base_url = source.config["base_url"]
    since = source.cursor or source.config["start_after"]  # check_source parsed start_after
    since_at = NAIVE_UTC.validate_python(since)
    now = clock.now()
    try:
        window = timedelta(days=int(source.config.get("window_days", 7)))
        # `before:` is a date, so tomorrow at most keeps today's posts in the search
        until = min(now + timedelta(days=1), since_at + window)
    except OverflowError as exc:
        raise PermanentError(str(exc)) from exc
    query = f"after:{since_at.date()} before:{until.date()}"
    newest: datetime | None = None
    for page in range(1, _MAX_PAGES + 1):
        check()
        raw = http.get_json(f"{base_url}/search.json", [("q", query), ("page", str(page))])
        search = _validated(SearchPageIn, raw, "search.json")
        grouped = search.grouped_search_result
        if grouped.error:  # upstream text stays in the log, out of PullResult and the API
            extra = {"tenant_id": source.tenant_id, "source_id": source.id}
            log.warning("discourse search error: %s", grouped.error, extra=extra)
            msg = "discourse search reported an error"
            raise PermanentError(msg)
        newest = max(
            [hit.created_at for hit in search.posts] + ([newest] if newest else []), default=None
        )
        final = not grouped.more_full_page_results
        cursor = _next_cursor(since_at, newest, until, now) if final else since
        yield PullPage(payloads=_fetch_posts(base_url, http, search, check), cursor=cursor)
        if final:
            return
    msg = (
        f"discourse source {source.id}: window exceeds {_MAX_PAGES} pages; about 500 posts per day"
        " is the hard limit of Discourse search; lower window_days via PATCH"
    )
    raise PermanentError(msg)


# 60 s overlap: a post committed late with an older timestamp is re-read, dedup absorbs the repeat.
# A window wholly in the past advances to its end, so an empty week does not stall the cursor.
def _next_cursor(since: datetime, newest: datetime | None, until: datetime, now: datetime) -> str:
    moved = max(newest - _OVERLAP, since) if newest else since
    return (max(moved, until) if until < now else moved).isoformat()


def _check_deadline(clock: Clock, deadline: datetime) -> None:
    if clock.now() > deadline:
        msg = "pull deadline exceeded"
        raise TransientError(msg)


def _fetch_posts(
    base_url: str, http: HttpClient, search: SearchPageIn, check: Callable[[], None]
) -> list[dict[str, Any]]:
    titles = {topic.id: topic.title for topic in search.topics}
    by_topic: defaultdict[int, list[SearchHitIn]] = defaultdict(list)
    for hit in search.posts:
        by_topic[hit.topic_id].append(hit)
    payloads: list[dict[str, Any]] = []
    for topic_id, hits in by_topic.items():
        headline = hits[0].topic_title_headline
        title = titles.get(topic_id) or (strip_tags(headline) if headline else None)
        wanted = {hit.id for hit in hits}
        posts: list[dict[str, Any]] = []
        for chunk in batched(sorted(wanted), _POSTS_PER_CALL):
            check()
            ids = [("post_ids[]", str(post_id)) for post_id in chunk]
            raw = http.get_json(f"{base_url}/t/{topic_id}/posts.json", ids)
            posts += _validated(TopicPostsIn, raw, "posts.json").post_stream.posts
        missing = wanted - {p["id"] for p in posts if isinstance(p.get("id"), int)}
        # a post can vanish between search and fetch; stop so the cursor does not pass it
        if missing:
            msg = f"topic {topic_id} omitted posts {sorted(missing)}"
            raise TransientError(msg)
        payloads += [post | {"topic_title": title} for post in posts]
    return payloads


def _validated[M: BaseModel](model: type[M], data: dict[str, Any], what: str) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        msg = f"unexpected response shape from {what}: {exc.error_count()} errors"
        raise TransientError(msg) from exc
