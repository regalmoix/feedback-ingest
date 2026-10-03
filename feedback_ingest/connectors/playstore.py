from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator
from pydantic.alias_generators import to_camel

from feedback_ingest.connectors.base import default_verify_signature, new_record
from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.errors import PermanentError
from feedback_ingest.domain.metadata import PlaystoreMetadata
from feedback_ingest.domain.models import FeedbackRecord, Source
from feedback_ingest.utils.hashing import payload_hash
from feedback_ingest.utils.time import NaiveUtc


class _In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, extra="ignore")


class _Timestamp(_In):
    seconds: NaiveUtc


class _UserComment(_In):
    text: str
    last_modified: _Timestamp
    star_rating: int
    reviewer_language: str | None = None
    device: str | None = None
    android_os_version: int | None = None
    app_version_name: str | None = None


class _Comment(_In):
    user_comment: _UserComment


class PlaystoreReviewIn(_In):
    review_id: str
    author_name: str | None = None
    comments: list[_Comment]

    @field_validator("comments", mode="before")
    @classmethod
    def _drop_developer_replies(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [c for c in value if not (isinstance(c, dict) and "developerComment" in c)]


class PlaystoreConnector:
    source_type: ClassVar[SourceType] = SourceType.PLAYSTORE
    version: ClassVar[int] = 1
    required_config: ClassVar[tuple[str, ...]] = ()

    def external_event_id(self, payload: Mapping[str, Any]) -> str:
        try:
            review = PlaystoreReviewIn.model_validate(payload)
            modified = review.comments[0].user_comment.last_modified.seconds
        except (ValidationError, IndexError):
            return payload_hash(dict(payload))
        return f"{review.review_id}:{modified.isoformat()}"

    def transform(self, source: Source, payload: Mapping[str, Any]) -> list[FeedbackRecord]:
        review = PlaystoreReviewIn.model_validate(payload)
        if not review.comments:  # a bad payload must not look like "no data"
            msg = "review has no user comment"
            raise PermanentError(msg)
        comment = review.comments[0].user_comment
        modified = comment.last_modified.seconds
        return [
            new_record(
                source,
                self,
                review.review_id,
                title=None,
                text=comment.text,
                author=review.author_name,
                language=comment.reviewer_language,
                rating=comment.star_rating,
                source_created_at=modified,
                source_updated_at=modified,
                deleted_at=None,
                metadata=PlaystoreMetadata(
                    app_version=comment.app_version_name,
                    device=comment.device,
                    android_os_version=comment.android_os_version,
                ),
            )
        ]

    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)
