from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any, ClassVar, Protocol
from uuid import NAMESPACE_URL, uuid5

from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.metadata import FrozenModel
from feedback_ingest.domain.models import FeedbackRecord, Source
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

    def pull(self, source: Source, http: HttpClient, now: datetime) -> Iterator[PullPage]: ...


def new_record(
    source: Source, connector: SourceConnector, external_id: str, **content: object
) -> FeedbackRecord:
    # kind comes from source_type; the pipeline replaces ingested_at with its clock
    return FeedbackRecord.model_validate(
        {
            "id": uuid5(NAMESPACE_URL, f"{source.id}:{external_id}").hex,
            "tenant_id": source.tenant_id,
            "source_id": source.id,
            "source_type": connector.source_type,
            "external_id": external_id,
            "connector_version": connector.version,
            "ingested_at": content["source_created_at"],
            **content,
        }
    )
