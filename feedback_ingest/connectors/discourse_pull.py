from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime, timedelta
from itertools import batched
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel, TypeAdapter, ValidationError

from feedback_ingest.connectors.base import PullPage
from feedback_ingest.connectors.discourse_models import SearchHitIn, SearchPageIn, TopicPostsIn
from feedback_ingest.domain.errors import TransformError, TransientError
from feedback_ingest.domain.models import NaiveUtc, Source
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.utils.html import strip_tags

_NAIVE_UTC: TypeAdapter[NaiveUtc] = TypeAdapter(NaiveUtc)
_OVERLAP = timedelta(seconds=60)
_MAX_PAGES = 20
_POSTS_PER_CALL = 20


# ponytail: every poll re-scans the whole window; store last post id per topic if Discourse
# volume grows. The cursor only advances on the final page because search order is not
# guaranteed oldest-first; a crash mid-run re-fetches from the old cursor (dedup absorbs it).
# ponytail: at most 20 search pages (~1000 posts) per window; a busier window raises after page 20
# with the cursor unmoved; lower config["window_days"] or page by date if that happens.
def pull_pages(source: Source, http: HttpClient, now: datetime) -> Iterator[PullPage]:
    base_url = config(source, "base_url")
    since = source.cursor or config(source, "start_after")
    try:
        since_at = _NAIVE_UTC.validate_python(since)
    except ValidationError:
        msg = f"discourse source {source.id} has an unparseable cursor {since!r}"
        raise TransformError(msg) from None
    window = timedelta(days=int(source.config.get("window_days", 7)))
    until = min(now + timedelta(days=1), since_at + window)
    query = f"after:{since_at.date()} before:{until.date()}"
    newest: datetime | None = None
    for page in range(1, _MAX_PAGES + 1):
        raw = http.get_json(f"{base_url}/search.json", {"q": query, "page": str(page)})
        search = _validated(SearchPageIn, raw, "search.json")
        grouped = search.grouped_search_result
        if grouped and grouped.error:
            msg = f"discourse search failed: {grouped.error}"
            raise TransformError(msg)
        newest = max(
            [hit.created_at for hit in search.posts] + ([newest] if newest else []), default=None
        )
        final = not (grouped and grouped.more_full_page_results)
        cursor = since
        if final:
            moved = max(newest - _OVERLAP, since_at) if newest else since_at
            cursor = (max(moved, until) if until < now else moved).isoformat()
        yield PullPage(payloads=_fetch_posts(base_url, http, search), cursor=cursor)
        if final:
            return
    msg = (
        f"discourse source {source.id}: window exceeds {_MAX_PAGES} pages; "
        "lower config['window_days']"
    )
    raise TransformError(msg)


def _fetch_posts(base_url: str, http: HttpClient, search: SearchPageIn) -> list[dict[str, Any]]:
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
            query = urlencode([("post_ids[]", post_id) for post_id in chunk])
            raw = http.get_json(f"{base_url}/t/{topic_id}/posts.json?{query}", {})
            posts += _validated(TopicPostsIn, raw, "posts.json").post_stream.posts
        missing = wanted - {post.get("id") for post in posts}
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


def config(source: Source, key: str) -> str:
    try:
        return source.config[key]
    except KeyError:
        msg = f"discourse source {source.id} needs config[{key!r}]"
        raise TransformError(msg) from None
