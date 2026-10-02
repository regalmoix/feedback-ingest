from typing import Any

from pydantic import BaseModel

from feedback_ingest.domain.models import NaiveUtc


class DiscoursePostIn(BaseModel):
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


class SearchHitIn(BaseModel):
    id: int
    topic_id: int
    created_at: NaiveUtc
    topic_title_headline: str | None = None


class _TopicIn(BaseModel):
    id: int
    title: str


class _GroupedIn(BaseModel):
    more_full_page_results: bool | None = None
    error: str | None = None


class SearchPageIn(BaseModel):
    posts: list[SearchHitIn]
    topics: list[_TopicIn] = []
    grouped_search_result: _GroupedIn | None = None


class _PostStreamIn(BaseModel):
    posts: list[dict[str, Any]]


class TopicPostsIn(BaseModel):
    post_stream: _PostStreamIn
