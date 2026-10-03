from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from feedback_ingest.connectors.base import SourceConnector, default_verify_signature, new_record
from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.errors import PermanentError
from feedback_ingest.domain.metadata import TwitterMetadata
from feedback_ingest.domain.models import FeedbackRecord, Source
from feedback_ingest.utils.hashing import payload_hash
from feedback_ingest.utils.time import NaiveUtc


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


class TwitterConnector(SourceConnector):
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
            raise PermanentError(msg)
        external_id = (history or [tweet.id])[0]
        return [
            new_record(
                source,
                self,
                external_id,
                title=None,
                text=tweet.text,
                author=f"@{tweet.author.username}",
                language=tweet.lang,
                rating=None,
                source_created_at=tweet.created_at,
                source_updated_at=None,
                deleted_at=None,
                metadata=TwitterMetadata(
                    country=tweet.country,
                    retweets=tweet.public_metrics.retweet_count,
                    likes=tweet.public_metrics.like_count,
                ),
            )
        ]

    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)
