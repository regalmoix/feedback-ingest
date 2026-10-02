from pydantic import TypeAdapter, ValidationError

from feedback_ingest.connectors.base import PullConnector, SourceConnector
from feedback_ingest.connectors.discourse import DiscourseConnector
from feedback_ingest.connectors.intercom import IntercomConnector
from feedback_ingest.connectors.playstore import PlaystoreConnector
from feedback_ingest.connectors.twitter import TwitterConnector
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import NaiveUtc, Source

_DISCOURSE = DiscourseConnector()
_ALL: tuple[SourceConnector, ...] = (
    _DISCOURSE,
    PlaystoreConnector(),
    TwitterConnector(),
    IntercomConnector(),
)
_PULL: tuple[PullConnector, ...] = (_DISCOURSE,)

CONNECTORS: dict[SourceType, SourceConnector] = {c.source_type: c for c in _ALL}
PULLERS: dict[SourceType, PullConnector] = {c.source_type: c for c in _PULL}
_NAIVE_UTC: TypeAdapter[NaiveUtc] = TypeAdapter(NaiveUtc)


def check_source(source: Source) -> None:
    if source.mode is not SourceMode.PULL:
        return
    if source.type not in PULLERS:
        msg = f"{source.type} cannot pull"
        raise ValueError(msg)
    for key in PULLERS[source.type].required_config:
        if key not in source.config:
            msg = f"{source.type} pull source needs config[{key!r}]"
            raise ValueError(msg)
    if "start_after" in source.config:
        try:
            _NAIVE_UTC.validate_python(source.config["start_after"])
        except ValidationError:
            msg = f"config['start_after'] is not a datetime: {source.config['start_after']!r}"
            raise ValueError(msg) from None
