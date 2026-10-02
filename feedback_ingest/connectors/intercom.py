from collections.abc import Mapping
from typing import Any, ClassVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, ValidationError

from feedback_ingest.connectors.base import default_verify_signature
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.metadata import IntercomMetadata
from feedback_ingest.domain.models import FeedbackRecord, Source
from feedback_ingest.utils.hashing import payload_hash
from feedback_ingest.utils.html import strip_tags
from feedback_ingest.utils.time import from_epoch


class _In(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Author(_In):
    name: str | None = None


class _Source(_In):
    subject: str | None = None
    body: str
    author: _Author


class _Part(_In):
    id: str
    body: str | None = None
    created_at: int
    author: _Author


class _Parts(_In):
    conversation_parts: list[_Part]


class _Tag(_In):
    name: str


class _Tags(_In):
    tags: list[_Tag]


class IntercomConversationIn(_In):
    id: str
    created_at: int
    updated_at: int
    state: str
    source: _Source
    conversation_parts: _Parts
    tags: _Tags


class IntercomEventIn(_In):
    topic: str
    data: dict[str, Any]


class IntercomConnector:
    source_type: ClassVar[SourceType] = SourceType.INTERCOM
    version: ClassVar[int] = 1

    def external_event_id(self, payload: dict[str, Any]) -> str:
        try:
            event = IntercomEventIn.model_validate(payload)
            item = IntercomConversationIn.model_validate(event.data.get("item"))
        except ValidationError:
            return payload_hash(payload)
        return f"{item.id}:{item.updated_at}"

    def transform(self, source: Source, payload: dict[str, Any]) -> list[FeedbackRecord]:
        event = IntercomEventIn.model_validate(payload)
        if not event.topic.startswith("conversation."):
            return []
        item = IntercomConversationIn.model_validate(event.data.get("item"))
        parts = sorted(item.conversation_parts.conversation_parts, key=lambda p: p.created_at)
        texts = [strip_tags(body or "") for body in (item.source.body, *(p.body for p in parts))]
        return [
            FeedbackRecord(
                id=uuid4().hex,
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
                source_created_at=from_epoch(item.created_at),
                source_updated_at=from_epoch(item.updated_at),
                ingested_at=from_epoch(item.created_at),
                deleted_at=None,
                connector_version=self.version,
                metadata=IntercomMetadata(
                    conversation_id=item.id,
                    part_count=len(parts),
                    tags=tuple(tag.name for tag in item.tags.tags),
                    state=item.state,
                ),
            )
        ]

    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        return default_verify_signature(secret, body, headers)
