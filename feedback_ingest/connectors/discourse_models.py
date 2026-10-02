from pydantic import BaseModel, ConfigDict

from feedback_ingest.domain.models import NaiveUtc


class _In(BaseModel):
    model_config = ConfigDict(extra="ignore")


class DiscoursePostIn(_In):
    id: int
    topic_id: int
    post_number: int
    username: str
    name: str | None = None
    created_at: NaiveUtc
    updated_at: NaiveUtc | None = None
    cooked: str
    topic_slug: str
    topic_title: str | None = None
    deleted_at: NaiveUtc | None = None
    like_count: int = 0


class SearchHitIn(_In):
    id: int
    topic_id: int
    created_at: NaiveUtc
    topic_title_headline: str | None = None
