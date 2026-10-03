from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from feedback_ingest.connectors.base import SourceConnector, default_verify_signature, new_record
from feedback_ingest.domain.enums import KIND_BY_RECORD_TYPE, SourceType
from feedback_ingest.domain.errors import PermanentError
from feedback_ingest.domain.metadata import CustomMetadata
from feedback_ingest.domain.models import FeedbackRecord, Source
from feedback_ingest.utils.hashing import payload_hash
from feedback_ingest.utils.time import NaiveUtc


class CustomRecordIn(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, extra="ignore")
    id: str
    type: str
    created_at: NaiveUtc  # epoch seconds (13-digit milliseconds too) or ISO 8601
    updated_at: NaiveUtc | None = None
    text: str
    title: str | None = None
    author: str | None = None
    language: str | None = None
    rating: int | None = None
    metadata: dict[str, str | float | bool] = {}


class CustomBatchIn(BaseModel):
    records: list[CustomRecordIn] = Field(min_length=1)


class CustomConnector(SourceConnector):
    source_type: ClassVar[SourceType] = SourceType.CUSTOM
    version: ClassVar[int] = 1
    required_config: ClassVar[tuple[str, ...]] = ()

    def external_event_id(self, payload: Mapping[str, Any]) -> str:
        return payload_hash(dict(payload))  # a batch is one delivery

    # ponytail: one bad record dead-letters the whole batch; split a batch into one raw event per
    # record at accept time if senders need partial acceptance
    def transform(self, source: Source, payload: Mapping[str, Any]) -> list[FeedbackRecord]:
        return [self._record(source, r) for r in CustomBatchIn.model_validate(payload).records]

    def _record(self, source: Source, record: CustomRecordIn) -> FeedbackRecord:
        if record.type not in KIND_BY_RECORD_TYPE:
            msg = f"unsupported record type {record.type[:40]}"
            raise PermanentError(msg)
        fields = dict(record.metadata)
        score = fields.pop("score", None)
        return new_record(
            source,
            self,
            record.id,
            title=record.title,
            text=record.text,
            author=record.author,
            language=record.language,
            rating=record.rating,
            source_created_at=record.created_at,
            source_updated_at=record.updated_at,
            deleted_at=None,
            kind=KIND_BY_RECORD_TYPE[record.type],
            metadata=CustomMetadata(record_type=record.type, score=score, fields=fields),
        )

    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)
