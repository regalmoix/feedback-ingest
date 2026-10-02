import json

import pytest
from helpers import KEY_A, fixture_body, memory_adapters, seed_source

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.utils.hashing import payload_hash


def test_accept_stores_a_pending_event_once(
    clock: FixedClock, caplog: pytest.LogCaptureFixture
) -> None:
    adapters = memory_adapters(clock)
    source = seed_source(adapters, "tenant-a", KEY_A)
    payload = json.loads(fixture_body(SourceType.PLAYSTORE, "review"))
    ingestion = IngestionService(adapters.queue, clock)

    first = ingestion.accept(source, payload)
    assert not first.duplicate
    assert first.raw_event_id
    event = adapters.queue.get(first.raw_event_id)
    assert event is not None
    assert (event.tenant_id, event.source_id) == (source.tenant_id, source.id)
    assert event.external_event_id == CONNECTORS[source.type].external_event_id(payload)
    assert event.payload == payload
    assert event.received_at == event.next_attempt_at == clock.now()
    assert event.status == EventStatus.PENDING
    [record] = [r for r in caplog.records if r.getMessage().startswith("accepted")]
    fields = ("raw_event_id", "tenant_id", "source_id", "duplicate")
    assert [vars(record)[k] for k in fields] == [event.id, source.tenant_id, source.id, False]

    again = ingestion.accept(source, payload)
    assert (again.raw_event_id, again.duplicate) == (None, True)
    assert adapters.queue.counts()[EventStatus.PENDING] == 1


def test_accept_stores_a_malformed_payload_keyed_by_its_hash(clock: FixedClock) -> None:
    adapters = memory_adapters(clock)
    source = seed_source(adapters, "tenant-a", KEY_A)
    payload = json.loads(fixture_body(SourceType.PLAYSTORE, "malformed"))
    result = IngestionService(adapters.queue, clock).accept(source, payload)
    assert result.raw_event_id
    event = adapters.queue.get(result.raw_event_id)
    assert event is not None
    assert event.external_event_id == payload_hash(payload)
