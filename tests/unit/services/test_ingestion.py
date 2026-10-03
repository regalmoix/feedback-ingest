import logging

import pytest
from helpers import KEY_A, load, seed_source

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.api.deps import Adapters
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import EventStatus, SourceType
from feedback_ingest.services.ingestion import IngestionService
from feedback_ingest.utils.hashing import payload_hash


def test_accept_stores_a_pending_event_once(
    adapters: Adapters, clock: FixedClock, caplog: pytest.LogCaptureFixture
) -> None:
    source = seed_source(adapters, "tenant-a", KEY_A)
    payload = load(SourceType.PLAYSTORE, "review")
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
    assert (again.raw_event_id, again.duplicate) == (event.id, True)
    assert adapters.queue.counts()[EventStatus.PENDING] == 1


def test_accept_stores_a_malformed_payload_keyed_by_its_hash(
    adapters: Adapters, clock: FixedClock
) -> None:
    source = seed_source(adapters, "tenant-a", KEY_A)
    payload = load(SourceType.PLAYSTORE, "malformed")
    result = IngestionService(adapters.queue, clock).accept(source, payload)
    assert result.raw_event_id
    event = adapters.queue.get(result.raw_event_id)
    assert event is not None
    assert event.external_event_id == payload_hash(payload)


def test_a_duplicate_of_a_dead_event_is_not_replayed_but_warns(
    adapters: Adapters, caplog: pytest.LogCaptureFixture
) -> None:
    source = seed_source(adapters, "tenant-a", KEY_A)
    payload = load(SourceType.PLAYSTORE, "malformed")
    ingestion = IngestionService(adapters.queue, adapters.clock)
    first = ingestion.accept(source, payload)
    [claimed] = adapters.queue.claim(adapters.clock.now(), 30, 1)
    assert adapters.queue.mark_dead(claimed, "bad")
    assert ingestion.accept(source, payload).duplicate
    assert adapters.queue.counts()[EventStatus.DEAD] == 1
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "dead raw event" in warning.getMessage()
    assert vars(warning)["raw_event_id"] == first.raw_event_id
