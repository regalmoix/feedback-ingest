from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any, ClassVar, NotRequired, Protocol, TypedDict, Unpack
from uuid import NAMESPACE_URL, uuid5

from feedback_ingest.domain.enums import KIND_BY_SOURCE, FeedbackKind, SourceType
from feedback_ingest.domain.metadata import FrozenModel, SourceMetadata
from feedback_ingest.domain.models import FeedbackRecord, Source
from feedback_ingest.ports.clock import Clock
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.utils import signing


class PullPage(FrozenModel):
    payloads: list[dict[str, Any]]
    cursor: str  # saved only after this page's raw rows are committed


def default_verify_signature(secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
    return signing.verify(secret, body, headers.get("X-Signature", ""))


class SourceConnector(Protocol):
    source_type: ClassVar[SourceType]
    version: ClassVar[int]
    required_config: ClassVar[tuple[str, ...]]

    def external_event_id(self, payload: Mapping[str, Any]) -> str: ...
    def transform(self, source: Source, payload: Mapping[str, Any]) -> list[FeedbackRecord]: ...
    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool: ...


class PullConnector(SourceConnector, Protocol):
    pull_config: ClassVar[tuple[str, ...]]  # extra config keys a pull-mode Source must have

    def pull(
        self, source: Source, http: HttpClient, clock: Clock, deadline: datetime
    ) -> Iterator[PullPage]: ...


class RecordContent(TypedDict):
    title: str | None
    text: str
    author: str | None
    language: str | None
    rating: int | None
    source_created_at: datetime
    source_updated_at: datetime | None
    deleted_at: datetime | None
    metadata: SourceMetadata
    kind: NotRequired[FeedbackKind]  # defaults to KIND_BY_SOURCE; custom passes its own


def new_record(
    source: Source, connector: SourceConnector, external_id: str, **content: Unpack[RecordContent]
) -> FeedbackRecord:
    # identity keys go last so content cannot override them; the pipeline stamps ingested_at
    return FeedbackRecord.model_validate(
        {
            "kind": KIND_BY_SOURCE.get(connector.source_type),
            **content,
            "id": uuid5(NAMESPACE_URL, f"{source.id}:{external_id}").hex,
            "tenant_id": source.tenant_id,
            "source_id": source.id,
            "source_type": connector.source_type,
            "external_id": external_id,
            "connector_version": connector.version,
            "ingested_at": content["source_created_at"],
        }
    )
