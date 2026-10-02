from collections.abc import Mapping
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError

from feedback_ingest.connectors.base import default_verify_signature
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.metadata import TwitterMetadata
from feedback_ingest.domain.models import FeedbackRecord, NaiveUtc, Source
from feedback_ingest.utils.hashing import payload_hash


class _In(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Author(_In):
    id: str
    username: str


class _PublicMetrics(_In):
    retweet_count: int = 0
    like_count: int = 0


class TweetIn(_In):
    id: str
    text: str
    created_at: NaiveUtc
    lang: str | None = None
    author: _Author
    edit_history_tweet_ids: list[str] = []
    public_metrics: _PublicMetrics = _PublicMetrics()
    country: str | None = None


class TwitterConnector:
    source_type: ClassVar[SourceType] = SourceType.TWITTER
    version: ClassVar[int] = 1

    def external_event_id(self, payload: dict[str, Any]) -> str:
        try:
            tweet = TweetIn.model_validate(payload)
        except ValidationError:
            return payload_hash(payload)
        return f"{tweet.id}:{tweet.created_at.isoformat()}"

    def transform(self, source: Source, payload: dict[str, Any]) -> list[FeedbackRecord]:
        tweet = TweetIn.model_validate(payload)
        handle = f"@{tweet.author.username}"
        return [
            FeedbackRecord(
                id=uuid4().hex,
                tenant_id=source.tenant_id,
                source_id=source.id,
                source_type=self.source_type,
                external_id=(tweet.edit_history_tweet_ids or [tweet.id])[0],
                kind=FeedbackKind.POST,
                title=None,
                text=tweet.text,
                author=handle,
                language=tweet.lang,
                rating=None,
                source_created_at=tweet.created_at,
                source_updated_at=None,
                ingested_at=tweet.created_at,
                deleted_at=None,
                connector_version=self.version,
                metadata=TwitterMetadata(
                    country=tweet.country,
                    retweets=tweet.public_metrics.retweet_count,
                    likes=tweet.public_metrics.like_count,
                    handle=handle,
                ),
            )
        ]

    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)
