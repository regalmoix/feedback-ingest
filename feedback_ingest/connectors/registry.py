from feedback_ingest.connectors.base import PullConnector, SourceConnector
from feedback_ingest.connectors.discourse import DiscourseConnector
from feedback_ingest.connectors.intercom import IntercomConnector
from feedback_ingest.connectors.playstore import PlaystoreConnector
from feedback_ingest.connectors.twitter import TwitterConnector
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source

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


def connector_for(source: Source) -> SourceConnector:
    return CONNECTORS[source.type]


def puller_for(source: Source) -> PullConnector:
    puller = PULLERS.get(source.type)
    if puller is None:
        msg = f"{source.type} cannot pull"
        raise ValueError(msg)
    return puller


def check_source(source: Source) -> None:
    if source.mode is SourceMode.PULL:
        puller_for(source)
