from collections.abc import Mapping
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from pydantic.alias_generators import to_camel

from feedback_ingest.connectors.base import default_verify_signature
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.metadata import PlaystoreMetadata
from feedback_ingest.domain.models import FeedbackRecord, Source
from feedback_ingest.utils.hashing import payload_hash
from feedback_ingest.utils.time import from_epoch


class _In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, extra="ignore")


class _Timestamp(_In):
    seconds: int


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
    comments: list[_Comment] = Field(min_length=1)

    @field_validator("comments", mode="before")
    @classmethod
    def _drop_developer_replies(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        return [c for c in value if not (isinstance(c, dict) and "developerComment" in c)]


class PlaystoreConnector:
    source_type: ClassVar[SourceType] = SourceType.PLAYSTORE
    version: ClassVar[int] = 1

    def external_event_id(self, payload: dict[str, Any]) -> str:
        try:
            review = PlaystoreReviewIn.model_validate(payload)
        except ValidationError:
            return payload_hash(payload)
        return f"{review.review_id}:{review.comments[0].user_comment.last_modified.seconds}"

    def transform(self, source: Source, payload: dict[str, Any]) -> list[FeedbackRecord]:
        review = PlaystoreReviewIn.model_validate(payload)
        comment = review.comments[0].user_comment
        modified = from_epoch(comment.last_modified.seconds)
        return [
            FeedbackRecord(
                id=uuid4().hex,
                tenant_id=source.tenant_id,
                source_id=source.id,
                source_type=self.source_type,
                external_id=review.review_id,
                kind=FeedbackKind.REVIEW,
                title=None,
                text=comment.text,
                author=review.author_name,
                language=comment.reviewer_language,
                rating=comment.star_rating,
                source_created_at=modified,
                source_updated_at=modified,
                ingested_at=modified,
                deleted_at=None,
                connector_version=self.version,
                metadata=PlaystoreMetadata(
                    app_version=comment.app_version_name,
                    device=comment.device,
                    android_os_version=comment.android_os_version,
                ),
            )
        ]

    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)
