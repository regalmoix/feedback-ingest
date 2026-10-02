from helpers import add_pull_source

from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import EventStatus
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pull import PullResult, PullService

WINDOW_END = "2026-02-08T00:00:00"  # start_after + the default 7-day window, already past


def service(adapters: Adapters, http: HttpClient | None = None) -> PullService:
    ingestion = IngestionService(adapters.queue, adapters.clock)
    return PullService(adapters.sources, ingestion, http or adapters.http, adapters.clock, 60)


def stored_cursor(adapters: Adapters, source_id: str) -> str | None:
    source = adapters.sources.get(source_id, tenant_id="tenant-a")
    assert source is not None
    return source.cursor


def test_two_pages_are_accepted_and_the_final_cursor_is_saved(adapters: Adapters) -> None:
    source = add_pull_source(adapters, "src-forum")
    result = service(adapters).sync(source)
    assert result == PullResult(
        source_id="src-forum", pages=2, accepted=4, duplicates=0, cursor=WINDOW_END, error=None
    )
    assert stored_cursor(adapters, "src-forum") == WINDOW_END
    assert adapters.queue.counts()[EventStatus.PENDING] == 4


def test_a_repeated_payload_is_counted_as_a_duplicate(adapters: Adapters) -> None:
    source = add_pull_source(adapters, "src-forum")
    pull = service(adapters)
    pull.sync(source)
    again = pull.sync(source)
    assert (again.accepted, again.duplicates, again.error) == (0, 4, None)
    assert adapters.queue.counts()[EventStatus.PENDING] == 4


def test_the_cursor_never_moves_backwards(adapters: Adapters) -> None:
    source = add_pull_source(adapters, "src-forum")
    later = "2026-02-20T00:00:00"
    adapters.sources.update_cursor(
        source.id, source.tenant_id, later
    )  # a concurrent sync got further
    assert service(adapters).sync(source).cursor == later
    assert stored_cursor(adapters, "src-forum") == later


def test_a_stored_cursor_with_an_offset_is_compared_as_an_instant(adapters: Adapters) -> None:
    source = add_pull_source(adapters, "src-forum")
    adapters.sources.update_cursor(
        source.id, source.tenant_id, "2026-02-08T05:00:00+05:30"
    )  # 2026-02-07T23:30Z
    assert service(adapters).sync(source).cursor == WINDOW_END
    assert stored_cursor(adapters, "src-forum") == WINDOW_END
