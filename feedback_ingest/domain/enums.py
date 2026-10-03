from enum import StrEnum
from typing import Literal


class SourceType(StrEnum):
    DISCOURSE = "discourse"
    PLAYSTORE = "playstore"
    TWITTER = "twitter"
    INTERCOM = "intercom"
    CUSTOM = "custom"


class SourceMode(StrEnum):
    PUSH = "push"
    PULL = "pull"


class FeedbackKind(StrEnum):
    REVIEW = "review"
    CONVERSATION = "conversation"
    POST = "post"
    SURVEY = "survey"


class EventStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    DEAD = "dead"


class UpsertOutcome(StrEnum):
    INSERTED = "inserted"
    UPDATED = "updated"
    SKIPPED_OLDER = "skipped_older"


KIND_BY_SOURCE: dict[SourceType, FeedbackKind] = {
    SourceType.PLAYSTORE: FeedbackKind.REVIEW,
    SourceType.INTERCOM: FeedbackKind.CONVERSATION,
    SourceType.TWITTER: FeedbackKind.POST,
    SourceType.DISCOURSE: FeedbackKind.POST,
}
CustomRecordType = Literal["REVIEW", "CONVERSATION", "FORUM_CONVERSATION_THREAD", "SURVEY"]
# the one exception: a custom (webhook) record carries its own kind, from the sender's record `type`
KIND_BY_RECORD_TYPE: dict[CustomRecordType, FeedbackKind] = {
    "REVIEW": FeedbackKind.REVIEW,
    "CONVERSATION": FeedbackKind.CONVERSATION,
    "FORUM_CONVERSATION_THREAD": FeedbackKind.POST,
    "SURVEY": FeedbackKind.SURVEY,
}
