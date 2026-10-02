from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from feedback_ingest.connectors.base import default_verify_signature, record_id
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.errors import TransformError
from feedback_ingest.domain.metadata import IntercomMetadata
from feedback_ingest.domain.models import FeedbackRecord, NaiveUtc, Source
from feedback_ingest.utils.hashing import payload_hash
from feedback_ingest.utils.html import strip_tags


class _Author(BaseModel):
    name: str | None = None


class _Source(BaseModel):
    subject: str | None = None
    body: str | None = None
    author: _Author


class _Part(BaseModel):
    body: str | None = None
    created_at: NaiveUtc


class _Parts(BaseModel):
    conversation_parts: list[_Part]


class _Tag(BaseModel):
    name: str


class _Tags(BaseModel):
    tags: list[_Tag]


class IntercomConversationIn(BaseModel):
    id: str
    created_at: NaiveUtc
    updated_at: NaiveUtc
    state: str
    source: _Source
    conversation_parts: _Parts
    tags: _Tags


class IntercomEventIn(BaseModel):
    topic: str
    data: dict[str, Any]


class IntercomConnector:
    source_type: ClassVar[SourceType] = SourceType.INTERCOM
    version: ClassVar[int] = 1
    required_config: ClassVar[tuple[str, ...]] = ()

    def external_event_id(self, payload: Mapping[str, Any]) -> str:
        try:
            event = IntercomEventIn.model_validate(payload)
            item = IntercomConversationIn.model_validate(event.data.get("item"))
        except ValidationError:
            return payload_hash(dict(payload))
        return f"{item.id}:{item.updated_at.isoformat()}:{payload_hash(event.data['item'])[:12]}"

    def transform(self, source: Source, payload: Mapping[str, Any]) -> list[FeedbackRecord]:
        event = IntercomEventIn.model_validate(payload)
        if event.topic == "ping":
            return []
        if not event.topic.startswith("conversation."):
            msg = f"unsupported topic {event.topic}"
            raise TransformError(msg)
        item = IntercomConversationIn.model_validate(event.data.get("item"))
        parts = sorted(item.conversation_parts.conversation_parts, key=lambda p: p.created_at)
        texts = [strip_tags(body or "") for body in (item.source.body, *(p.body for p in parts))]
        return [
            FeedbackRecord(
                id=record_id(source.id, item.id),
                tenant_id=source.tenant_id,
                source_id=source.id,
                source_type=self.source_type,
                external_id=item.id,
                kind=FeedbackKind.CONVERSATION,
                title=item.source.subject,
                text="\n\n".join(t for t in texts if t),
                author=item.source.author.name,
                language=None,
                rating=None,
                source_created_at=item.created_at,
                source_updated_at=item.updated_at,
                ingested_at=item.created_at,
                deleted_at=None,
                connector_version=self.version,
                metadata=IntercomMetadata(
                    part_count=len(parts),
                    tags=tuple(tag.name for tag in item.tags.tags),
                    state=item.state,
                ),
            )
        ]

    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)
