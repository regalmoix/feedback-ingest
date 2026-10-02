from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime

import httpx
import pytest
from api.conftest import memory_adapters

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.services.pipeline import PipelineService
from feedback_ingest.services.pull import PullService
from feedback_ingest.services.worker import WorkerService

META = Source(
    id="src-meta",
    tenant_id="tenant-live",
    type=SourceType.DISCOURSE,
    name="meta.discourse.org",
    mode=SourceMode.PULL,
    config={
        "base_url": "https://meta.discourse.org",
        "start_after": "2021-01-01",
        "window_days": "3",
    },
    cursor=None,
)


@pytest.fixture
def adapters() -> Iterator[Adapters]:
    transport = httpx.HTTPTransport()  # owned here so the pool is closed under -W error
    # any clock after the window gives the same closed window, so the result is stable
    yield replace(
        memory_adapters(FixedClock(datetime(2026, 1, 1))), http=HttpxClient(transport=transport)
    )
    transport.close()


@pytest.mark.live
def test_a_closed_window_on_meta_discourse_ingests_once(adapters: Adapters) -> None:
    a = adapters
    a.sources.add(META)
    pull = PullService(a.sources, IngestionService(a.queue, a.clock), a.http, a.clock)
    pipeline = PipelineService(a.sources, a.feedback, a.queue, a.clock, 5, 300)
    worker = WorkerService(a.queue, pipeline, a.clock, 0, lease_seconds=30, batch=50)

    first = pull.sync(META)
    assert first.error is None
    assert first.accepted >= 1
    while worker.run_once():
        pass
    assert len(a.feedback.list_for_tenant(META.tenant_id, limit=10_000)) == first.accepted

    again = pull.sync(META)  # the original cursor, so the same window as the first sync
    assert (again.error, again.accepted, again.duplicates) == (None, 0, first.accepted)
