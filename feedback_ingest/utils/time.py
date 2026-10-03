from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, TypeAdapter


def to_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    try:
        return value.astimezone(UTC).replace(tzinfo=None)
    # year-9999 inputs; the guards in registry.py and discourse_pull.py exist because they add a
    # timedelta to a value that already passed this validation
    except OverflowError as exc:
        raise ValueError(str(exc)) from exc


NaiveUtc = Annotated[datetime, AfterValidator(to_naive_utc)]
NAIVE_UTC: TypeAdapter[NaiveUtc] = TypeAdapter(NaiveUtc)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC).replace(tzinfo=None)
