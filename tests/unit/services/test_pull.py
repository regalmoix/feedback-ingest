from datetime import datetime

import pytest
from helpers import KEY_A, add_pull_source, discourse_http, memory_adapters, seed_source

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import EventStatus, SourceMode
from feedback_ingest.ports.http import HttpClient
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pull import ConfigError, PullResult, PullService

NOW = datetime(2026, 3, 1, 12, 0)
WINDOW_END = "2026-02-08T00:00:00"  # start_after + the default 7-day window, already past


@pytest.fixture
def adapters() -> Adapters:
    a = memory_adapters(FixedClock(NOW))
    seed_source(a, "tenant-a", KEY_A)
    return a


def _service(adapters: Adapters, http: HttpClient | None = None) -> PullService:
    ingestion = IngestionService(adapters.queue, adapters.clock)
    return PullService(adapters.sources, ingestion, http or discourse_http(), adapters.clock)


def _stored_cursor(adapters: Adapters, source_id: str) -> str | None:
    source = adapters.sources.get(source_id, tenant_id="tenant-a")
    assert source is not None
    return source.cursor


def test_two_pages_are_accepted_and_the_final_cursor_is_saved(adapters: Adapters) -> None:
    source = add_pull_source(adapters, "src-forum")
    result = _service(adapters).sync(source)
    assert result == PullResult(
        source_id="src-forum", pages=2, accepted=4, duplicates=0, cursor=WINDOW_END, error=None
    )
    assert _stored_cursor(adapters, "src-forum") == WINDOW_END
    assert adapters.queue.counts()[EventStatus.PENDING] == 4


def test_a_repeated_payload_is_counted_as_a_duplicate(adapters: Adapters) -> None:
    source = add_pull_source(adapters, "src-forum")
    service = _service(adapters)
    service.sync(source)
    again = service.sync(source)
    assert (again.accepted, again.duplicates, again.error) == (0, 4, None)
    assert adapters.queue.counts()[EventStatus.PENDING] == 4


def test_the_cursor_never_moves_backwards(adapters: Adapters) -> None:
    source = add_pull_source(adapters, "src-forum")
    later = "2026-02-20T00:00:00"
    adapters.sources.update_cursor(source.id, later)  # a concurrent sync got further
    assert _service(adapters).sync(source).cursor == later
    assert _stored_cursor(adapters, "src-forum") == later


def test_a_push_only_source_raises_config_error(adapters: Adapters) -> None:
    push_only = adapters.sources.list_by_mode(SourceMode.PUSH)[0]
    with pytest.raises(ConfigError, match="push-only"):
        _service(adapters).sync(push_only)
    forum = add_pull_source(adapters, "src-forum").model_copy(update={"mode": SourceMode.PUSH})
    with pytest.raises(ConfigError, match="push source"):
        _service(adapters).sync(forum)
