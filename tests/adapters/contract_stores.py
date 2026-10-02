from datetime import timedelta

import pytest
from contract import (
    SOURCE_A1,
    SOURCE_A2,
    SOURCE_B1,
    TENANT_A,
    TENANT_B,
    Adapters,
    Case,
    ist,
    record,
    seed,
)
from sqlalchemy.exc import IntegrityError

from feedback_ingest.domain.enums import EventStatus, FeedbackKind, SourceMode, SourceType
from feedback_ingest.domain.errors import NotFoundError
from feedback_ingest.domain.metadata import TwitterMetadata


def same_external_id_in_two_sources_is_two_rows(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.feedback.upsert(record(SOURCE_A1, "r1", now))
    a.feedback.upsert(record(SOURCE_A2, "r1", now))
    rows = a.feedback.list_for_tenant(TENANT_A.id)
    assert sorted(r.source_id for r in rows) == [SOURCE_A1.id, SOURCE_A2.id]


def tenants_are_isolated(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.feedback.upsert(record(SOURCE_A1, "r1", now))
    a.feedback.upsert(record(SOURCE_B1, "r2", now))
    assert [r.external_id for r in a.feedback.list_for_tenant(TENANT_B.id)] == ["r2"]
    assert a.feedback.list_for_tenant(TENANT_B.id, source_id=SOURCE_A1.id) == []
    assert a.sources.get(SOURCE_A1.id, TENANT_B.id) is None
    assert a.sources.get(SOURCE_A1.id, TENANT_A.id) == SOURCE_A1


def filters_and_lookups_match(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    later = now + timedelta(hours=1)
    tweet = {"source_type": SourceType.TWITTER, "kind": FeedbackKind.POST}
    meta = TwitterMetadata(country=None, retweets=0, handle="@a")
    a.feedback.upsert(record(SOURCE_A1, "r1", now))
    a.feedback.upsert(record(SOURCE_A2, "r2", later, **tweet, metadata=meta))
    by = a.feedback.list_for_tenant
    assert [r.external_id for r in by(TENANT_A.id, source_id=SOURCE_A2.id)] == ["r2"]
    assert [r.external_id for r in by(TENANT_A.id, kind=FeedbackKind.REVIEW)] == ["r1"]
    assert [r.external_id for r in by(TENANT_A.id, since=later)] == ["r2"]
    assert [r.external_id for r in by(TENANT_A.id, since=ist(later))] == ["r2"]
    assert [r.external_id for r in by(TENANT_A.id, limit=1)] == ["r1"]
    assert a.tenants.get_by_api_key_hash("hash-b") == TENANT_B
    assert a.tenants.get_by_api_key_hash("nope") is None
    assert a.sources.list_for_tenant(TENANT_A.id) == [SOURCE_A1, SOURCE_A2]
    a.sources.update_cursor(SOURCE_A2.id, "2026-01-01T00:00:00")
    assert [s.cursor for s in a.sources.list_by_mode(SourceMode.PULL)] == ["2026-01-01T00:00:00"]


def duplicates_and_unknown_ids_raise(a: Adapters) -> None:
    seed(a)
    for duplicate in (TENANT_A, TENANT_A.model_copy(update={"id": "other"})):
        with pytest.raises((ValueError, IntegrityError)):
            a.tenants.add(duplicate)
    with pytest.raises((ValueError, IntegrityError)):
        a.sources.add(SOURCE_A1)
    with pytest.raises(NotFoundError):
        a.sources.update_cursor("missing", "cursor")


def list_limits_below_one_raise(a: Adapters) -> None:
    seed(a)
    for limit in (0, -1):
        with pytest.raises(ValueError, match="limit"):
            a.feedback.list_for_tenant(TENANT_A.id, limit=limit)
        with pytest.raises(ValueError, match="limit"):
            a.queue.list_by_status(EventStatus.PENDING, limit=limit)


STORE_CASES: list[Case] = [
    same_external_id_in_two_sources_is_two_rows,
    tenants_are_isolated,
    filters_and_lookups_match,
    duplicates_and_unknown_ids_raise,
    list_limits_below_one_raise,
]
