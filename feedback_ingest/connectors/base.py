from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any, ClassVar, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict

from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.models import FeedbackRecord, Source
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.utils import signing


class PullPage(BaseModel):
    model_config = ConfigDict(frozen=True)
    payloads: list[dict[str, Any]]
    cursor: str  # saved only after this page's raw rows are committed


def default_verify_signature(secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
    return signing.verify(secret, body, headers.get("X-Signature", ""))


def record_id(source_id: str, external_id: str) -> str:
    return uuid5(NAMESPACE_URL, f"{source_id}:{external_id}").hex


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
