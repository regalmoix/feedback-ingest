from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from feedback_ingest.domain.enums import SourceType


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class DiscourseMetadata(FrozenModel):
    source_type: Literal[SourceType.DISCOURSE] = SourceType.DISCOURSE
    topic_id: int
    post_number: int
    like_count: int
    url: str


class PlaystoreMetadata(FrozenModel):
    source_type: Literal[SourceType.PLAYSTORE] = SourceType.PLAYSTORE
    app_version: str | None
    device: str | None
    android_os_version: int | None = None


class TwitterMetadata(FrozenModel):
    source_type: Literal[SourceType.TWITTER] = SourceType.TWITTER
    country: str | None
    retweets: int
    likes: int = 0


class IntercomMetadata(FrozenModel):
    source_type: Literal[SourceType.INTERCOM] = SourceType.INTERCOM
    part_count: int
    tags: tuple[str, ...]
    state: str | None = None


SourceMetadata = Annotated[
    DiscourseMetadata | PlaystoreMetadata | TwitterMetadata | IntercomMetadata,
    Field(discriminator="source_type"),
]
