from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt

from feedback_ingest.domain.enums import CustomRecordType, SourceType


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class DiscourseMetadata(FrozenModel):
    source_type: Literal[SourceType.DISCOURSE] = SourceType.DISCOURSE
    topic_id: PositiveInt
    post_number: PositiveInt
    like_count: NonNegativeInt
    url: str


class PlaystoreMetadata(FrozenModel):
    source_type: Literal[SourceType.PLAYSTORE] = SourceType.PLAYSTORE
    app_version: str | None
    device: str | None
    android_os_version: int | None = None


class TwitterMetadata(FrozenModel):
    source_type: Literal[SourceType.TWITTER] = SourceType.TWITTER
    country: str | None
    retweets: NonNegativeInt
    likes: NonNegativeInt = 0


class IntercomMetadata(FrozenModel):
    source_type: Literal[SourceType.INTERCOM] = SourceType.INTERCOM
    part_count: NonNegativeInt
    tags: tuple[str, ...]
    state: str | None = None


class CustomMetadata(FrozenModel):
    source_type: Literal[SourceType.CUSTOM] = SourceType.CUSTOM
    record_type: CustomRecordType
    score: float | None = None
    fields: dict[str, str | float | bool] = {}


SourceMetadata = Annotated[
    DiscourseMetadata | PlaystoreMetadata | TwitterMetadata | IntercomMetadata | CustomMetadata,
    Field(discriminator="source_type"),
]
