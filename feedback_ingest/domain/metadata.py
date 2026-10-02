from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from feedback_ingest.domain.enums import SourceType


class _Metadata(BaseModel):
    model_config = ConfigDict(frozen=True)


class DiscourseMetadata(_Metadata):
    source_type: Literal[SourceType.DISCOURSE] = SourceType.DISCOURSE
    topic_id: int
    post_number: int
    like_count: int
    topic_title: str
    url: str


class PlaystoreMetadata(_Metadata):
    source_type: Literal[SourceType.PLAYSTORE] = SourceType.PLAYSTORE
    app_version: str | None
    device: str | None
    country: str | None


class TwitterMetadata(_Metadata):
    source_type: Literal[SourceType.TWITTER] = SourceType.TWITTER
    country: str | None
    retweets: int
    handle: str


class IntercomMetadata(_Metadata):
    source_type: Literal[SourceType.INTERCOM] = SourceType.INTERCOM
    conversation_id: str
    part_count: int
    tags: tuple[str, ...]


SourceMetadata = Annotated[
    DiscourseMetadata | PlaystoreMetadata | TwitterMetadata | IntercomMetadata,
    Field(discriminator="source_type"),
]
