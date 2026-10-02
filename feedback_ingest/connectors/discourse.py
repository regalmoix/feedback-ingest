from collections import defaultdict
from collections.abc import Iterator, Mapping
from datetime import datetime, timedelta
from itertools import count
from typing import Any, ClassVar
from urllib.parse import urlencode
from uuid import uuid4

from pydantic import TypeAdapter, ValidationError

from feedback_ingest.connectors.base import PullPage, default_verify_signature
from feedback_ingest.connectors.discourse_models import DiscoursePostIn, SearchHitIn
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.errors import TransformError
from feedback_ingest.domain.metadata import DiscourseMetadata
from feedback_ingest.domain.models import FeedbackRecord, Source
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.utils.hashing import payload_hash
from feedback_ingest.utils.html import strip_tags

_HITS = TypeAdapter(list[SearchHitIn])
_PAGE_SIZE = 50
_OVERLAP = timedelta(seconds=60)


class DiscourseConnector:
    source_type: ClassVar[SourceType] = SourceType.DISCOURSE
    version: ClassVar[int] = 1

    def external_event_id(self, payload: dict[str, Any]) -> str:
        try:
            post = DiscoursePostIn.model_validate(payload)
        except ValidationError:
            return payload_hash(payload)
        return f"{post.id}:{(post.updated_at or post.created_at).isoformat()}"

    def transform(self, source: Source, payload: dict[str, Any]) -> list[FeedbackRecord]:
        post = DiscoursePostIn.model_validate(payload)
        url = (
            f"{_config(source, 'base_url')}/t/{post.topic_slug}/{post.topic_id}/{post.post_number}"
        )
        return [
            FeedbackRecord(
                id=uuid4().hex,
                tenant_id=source.tenant_id,
                source_id=source.id,
                source_type=self.source_type,
                external_id=str(post.id),
                kind=FeedbackKind.POST,
                title=post.topic_title,
                text=strip_tags(post.cooked),
                author=post.name or post.username,
                language=None,
                rating=None,
                source_created_at=post.created_at,
                source_updated_at=post.updated_at,
                ingested_at=post.created_at,
                deleted_at=post.deleted_at,
                connector_version=self.version,
                metadata=DiscourseMetadata(
                    topic_id=post.topic_id,
                    post_number=post.post_number,
                    like_count=post.like_count,
                    topic_title=post.topic_title,
                    url=url,
                ),
            )
        ]

    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)

    # ponytail: full re-scan of each search page; store last post id per topic if Discourse
    # volume grows. The cursor only advances on the final page because search order is not
    # guaranteed oldest-first; a crash mid-run re-fetches from the old cursor (dedup absorbs it).
    def pull(self, source: Source, http: HttpClient, now: datetime) -> Iterator[PullPage]:
        base_url = _config(source, "base_url")
        since = source.cursor or _config(source, "start_after")
        until = (now + timedelta(days=1)).date()
        query = f"after:{datetime.fromisoformat(since).date()} before:{until}"
        newest: datetime | None = None
        for page in count(1):
            search = http.get_json(f"{base_url}/search.json", {"q": query, "page": str(page)})
            hits = _HITS.validate_python(search.get("posts", []))
            seen = [hit.created_at for hit in hits] + ([newest] if newest else [])
            newest = max(seen, default=None)
            final = len(hits) < _PAGE_SIZE
            cursor = (newest - _OVERLAP).isoformat() if final and newest else since
            yield PullPage(payloads=_fetch_posts(base_url, http, hits), cursor=cursor)
            if final:
                return


def _fetch_posts(base_url: str, http: HttpClient, hits: list[SearchHitIn]) -> list[dict[str, Any]]:
    by_topic: defaultdict[int, list[SearchHitIn]] = defaultdict(list)
    for hit in hits:
        by_topic[hit.topic_id].append(hit)
    payloads: list[dict[str, Any]] = []
    for topic_id, topic_hits in by_topic.items():
        post_ids = urlencode([("post_ids[]", hit.id) for hit in topic_hits])
        topic = http.get_json(f"{base_url}/t/{topic_id}/posts.json?{post_ids}", {})
        headline = topic_hits[0].topic_title_headline
        title = strip_tags(headline) if headline else None
        payloads += [post | {"topic_title": title} for post in topic["post_stream"]["posts"]]
    return payloads


def _config(source: Source, key: str) -> str:
    try:
        return source.config[key]
    except KeyError:
        msg = f"discourse source {source.id} needs config[{key!r}]"
        raise TransformError(msg) from None
