from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from feedback_ingest.connectors.base import default_verify_signature, record_id
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.errors import TransformError
from feedback_ingest.domain.metadata import TwitterMetadata
from feedback_ingest.domain.models import FeedbackRecord, NaiveUtc, Source
from feedback_ingest.utils.hashing import payload_hash


class _Author(BaseModel):
    username: str


class _PublicMetrics(BaseModel):
    retweet_count: int = 0
    like_count: int = 0


class TweetIn(BaseModel):
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
    required_config: ClassVar[tuple[str, ...]] = ()

    def external_event_id(self, payload: Mapping[str, Any]) -> str:
        try:
            tweet = TweetIn.model_validate(payload)
        except ValidationError:
            return payload_hash(dict(payload))
        return f"{tweet.id}:{tweet.created_at.isoformat()}"

    def transform(self, source: Source, payload: Mapping[str, Any]) -> list[FeedbackRecord]:
        tweet = TweetIn.model_validate(payload)
        history = tweet.edit_history_tweet_ids
        if history and tweet.id not in history:
            msg = f"tweet {tweet.id} is missing from its own edit_history_tweet_ids"
            raise TransformError(msg)
        external_id = (history or [tweet.id])[0]
        return [
            FeedbackRecord(
                id=record_id(source.id, external_id),
                tenant_id=source.tenant_id,
                source_id=source.id,
                source_type=self.source_type,
                external_id=external_id,
                kind=FeedbackKind.POST,
                title=None,
                text=tweet.text,
                author=f"@{tweet.author.username}",
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
                ),
            )
        ]

    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)
