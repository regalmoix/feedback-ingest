from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any, ClassVar

from pydantic import ValidationError

from feedback_ingest.connectors.base import (
    PullConnector,
    PullPage,
    default_verify_signature,
    new_record,
)
from feedback_ingest.connectors.discourse_models import DiscoursePostIn
from feedback_ingest.connectors.discourse_pull import pull_pages
from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.metadata import DiscourseMetadata
from feedback_ingest.domain.models import FeedbackRecord, Source
from feedback_ingest.ports.clock import Clock
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.utils.hashing import payload_hash
from feedback_ingest.utils.html import strip_tags


class DiscourseConnector(PullConnector):
    source_type: ClassVar[SourceType] = SourceType.DISCOURSE
    version: ClassVar[int] = 1
    required_config: ClassVar[tuple[str, ...]] = ("base_url",)
    pull_config: ClassVar[tuple[str, ...]] = ("start_after",)

    def external_event_id(self, payload: Mapping[str, Any]) -> str:
        try:
            post = DiscoursePostIn.model_validate(payload)
        except ValidationError:
            return payload_hash(dict(payload))
        return f"{post.id}:{(post.deleted_at or post.updated_at or post.created_at).isoformat()}"

    def transform(self, source: Source, payload: Mapping[str, Any]) -> list[FeedbackRecord]:
        post = DiscoursePostIn.model_validate(payload)
        url = f"{source.config['base_url']}/t/{post.topic_slug}/{post.topic_id}/{post.post_number}"
        return [
            new_record(
                source,
                self,
                str(post.id),
                title=post.topic_title,
                text=strip_tags(post.cooked),
                author=post.name or post.username,
                language=None,
                rating=None,
                source_created_at=post.created_at,
                source_updated_at=post.updated_at,
                deleted_at=post.deleted_at,
                metadata=DiscourseMetadata(
                    topic_id=post.topic_id,
                    post_number=post.post_number,
                    like_count=post.like_count,
                    url=url,
                ),
            )
        ]

    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)

    def pull(
        self, source: Source, http: HttpClient, clock: Clock, deadline: datetime
    ) -> Iterator[PullPage]:
        return pull_pages(source, http, clock, deadline)
