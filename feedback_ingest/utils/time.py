from datetime import UTC, datetime


def to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)


def from_epoch(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, UTC).replace(tzinfo=None)
