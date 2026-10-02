from enum import StrEnum


class SourceType(StrEnum):
    DISCOURSE = "discourse"
    PLAYSTORE = "playstore"
    TWITTER = "twitter"
    INTERCOM = "intercom"


class SourceMode(StrEnum):
    PUSH = "push"
    PULL = "pull"


class FeedbackKind(StrEnum):
    REVIEW = "review"
    CONVERSATION = "conversation"
    POST = "post"


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
