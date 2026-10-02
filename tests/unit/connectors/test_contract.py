import copy
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
from connector_fixtures import SECRET, fixture_names, load, source
from pydantic import ValidationError

from feedback_ingest.adapters.memory.queue import MemoryRawEventQueue
from feedback_ingest.adapters.memory.stores import MemoryFeedbackStore
from feedback_ingest.connectors.base import SourceConnector
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.models import FeedbackRecord, RawEvent
from feedback_ingest.utils.hashing import payload_hash
from feedback_ingest.utils.signing import sign

FIXTURE_CASES = [(t, name) for t in SourceType for name in fixture_names(t)]
VALID_CASES = [(t, name) for t, name in FIXTURE_CASES if name != "malformed"]
JUNK: list[dict[str, Any]] = [
    {},
    {"id": None},
    {"comments": "x"},
    {"data": []},
    {"data": {"item": 5}},
]
NOW = datetime(2026, 3, 1)  # noqa: DTZ001  naive UTC is the storage convention


def _ids(case: tuple[SourceType, str]) -> str:
    return f"{case[0]}/{case[1]}"


@pytest.mark.parametrize("case", VALID_CASES, ids=_ids)
def test_transform_is_deterministic_and_stamps_identity(case: tuple[SourceType, str]) -> None:
    source_type = case[0]
    connector, src, payload = CONNECTORS[source_type], source(source_type), load(*case)
    records = connector.transform(src, payload)
    again = connector.transform(src, copy.deepcopy(payload))
    assert [r.model_dump(exclude={"id"}) for r in records] == [
        r.model_dump(exclude={"id"}) for r in again
    ]
    for record in records:
        assert record.source_type == record.metadata.source_type == source_type
        assert (record.tenant_id, record.source_id) == (src.tenant_id, src.id)
        assert record.connector_version == connector.version
        assert record.ingested_at == record.source_created_at
    assert connector.external_event_id(payload) == connector.external_event_id(
        copy.deepcopy(payload)
    )


@pytest.mark.parametrize("connector", CONNECTORS.values(), ids=lambda c: c.source_type)
def test_external_event_id_never_raises(connector: SourceConnector) -> None:
    for payload in [load(*case) for case in FIXTURE_CASES] + JUNK:
        assert connector.external_event_id(payload)


@pytest.mark.parametrize("source_type", list(SourceType))
def test_malformed_payload_raises_validation_error(source_type: SourceType) -> None:
    connector, payload = CONNECTORS[source_type], load(source_type, "malformed")
    with pytest.raises(ValidationError):
        connector.transform(source(source_type), payload)
    assert connector.external_event_id(payload) == payload_hash(payload)


@pytest.mark.parametrize("source_type", list(SourceType))
def test_an_edit_is_a_new_raw_event_and_the_newer_text_wins(source_type: SourceType) -> None:
    connector, src = CONNECTORS[source_type], source(source_type)
    by_item: defaultdict[str, list[tuple[RawEvent, FeedbackRecord]]] = defaultdict(list)
    for name in fixture_names(source_type):
        if name == "malformed":
            continue
        payload = load(source_type, name)
        event = RawEvent(
            id=uuid4().hex,
            tenant_id=src.tenant_id,
            source_id=src.id,
            external_event_id=connector.external_event_id(payload),
            payload=payload,
            received_at=NOW,
            next_attempt_at=NOW,
        )
        for record in connector.transform(src, payload):
            by_item[record.external_id].append((event, record))
    edits = [versions for versions in by_item.values() if len(versions) > 1]
    assert edits, f"{source_type} needs an edited fixture"
    for versions in edits:
        queue = MemoryRawEventQueue()
        assert all(queue.enqueue(event) for event, _ in versions)
        newest = max((record for _, record in versions), key=lambda r: r.version_at)
        for ordered in (versions, versions[::-1]):
            store = MemoryFeedbackStore()
            for _, record in ordered:
                store.upsert(record)
            [stored] = store.list_for_tenant(src.tenant_id, include_deleted=True)
            assert stored.text == newest.text


@pytest.mark.parametrize("connector", CONNECTORS.values(), ids=lambda c: c.source_type)
def test_verify_signature_accepts_signed_body_and_rejects_tampered(
    connector: SourceConnector,
) -> None:
    body = b'{"id": 1}'
    headers = {"X-Signature": sign(SECRET, body)}
    assert connector.verify_signature(SECRET, body, headers)
    assert not connector.verify_signature(SECRET, b'{"id": 2}', headers)
    assert not connector.verify_signature(SECRET, body, {})
