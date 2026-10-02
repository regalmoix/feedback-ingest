from datetime import UTC, datetime


def to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    try:
        return value.astimezone(UTC).replace(tzinfo=None)
    except OverflowError as exc:
        raise ValueError(str(exc)) from exc


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
