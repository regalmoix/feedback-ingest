from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import Any, ClassVar, Protocol

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


class SourceConnector(Protocol):
    source_type: ClassVar[SourceType]
    version: ClassVar[int]

    def external_event_id(self, payload: dict[str, Any]) -> str: ...
    def transform(self, source: Source, payload: dict[str, Any]) -> list[FeedbackRecord]: ...
    def verify_signature(self, secret: str, body: bytes, headers: Mapping[str, str]) -> bool: ...


class PullConnector(SourceConnector, Protocol):
    def pull(self, source: Source, http: HttpClient, now: datetime) -> Iterator[PullPage]: ...
