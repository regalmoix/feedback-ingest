from datetime import timedelta

import pytest
from contract import (
    SOURCE_A1,
    SOURCE_A2,
    SOURCE_B1,
    TENANT_A,
    TENANT_B,
    Case,
    record,
    seed,
)
from sqlalchemy.exc import IntegrityError

from feedback_ingest.api.deps import Adapters
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
    assert a.sources.get_by_id(SOURCE_A1.id) == SOURCE_A1
    assert a.sources.get_by_id("missing") is None


def filters_and_lookups_match(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    later = now + timedelta(hours=1)
    meta = TwitterMetadata(country=None, retweets=0)
    a.feedback.upsert(record(SOURCE_A1, "r1", now))
    a.feedback.upsert(record(SOURCE_A2, "r2", later, source_type=SourceType.TWITTER, metadata=meta))
    by = a.feedback.list_for_tenant
    assert [r.external_id for r in by(TENANT_A.id, source_id=SOURCE_A2.id)] == ["r2"]
    assert [r.external_id for r in by(TENANT_A.id, kind=FeedbackKind.REVIEW)] == ["r1"]
    assert [r.external_id for r in by(TENANT_A.id, since=later)] == ["r2"]
    assert [r.external_id for r in by(TENANT_A.id, limit=1)] == ["r1"]
    assert a.tenants.get_by_api_key_hash("hash-b") == TENANT_B
    assert a.tenants.get_by_api_key_hash("nope") is None
    assert a.sources.list_for_tenant(TENANT_A.id) == [SOURCE_A1, SOURCE_A2]
    a.sources.update_cursor(SOURCE_A2.id, TENANT_A.id, "2026-01-01T00:00:00")
    assert [s.cursor for s in a.sources.list_enabled(SourceMode.PULL)] == ["2026-01-01T00:00:00"]


def duplicates_and_unknown_ids_raise(a: Adapters) -> None:
    seed(a)
    same_name = TENANT_A.model_copy(update={"id": "other", "api_key_hash": "hash-other"})
    for duplicate in (TENANT_A, TENANT_A.model_copy(update={"id": "other"}), same_name):
        with pytest.raises(ValueError, match="duplicate tenant"):
            a.tenants.add(duplicate)
    with pytest.raises((ValueError, IntegrityError)):
        a.sources.add(SOURCE_A1)
    for source_id, tenant_id in (("missing", TENANT_A.id), (SOURCE_A2.id, TENANT_B.id)):
        with pytest.raises(NotFoundError):
            a.sources.update_cursor(source_id, tenant_id, "cursor")
        with pytest.raises(NotFoundError):
            a.sources.set_config(source_id, tenant_id, {})
    a.sources.set_config(SOURCE_A2.id, TENANT_A.id, {"window_days": "2"})
    assert a.sources.get_by_id(SOURCE_A2.id) == SOURCE_A2.model_copy(
        update={"config": {"window_days": "2"}}
    )


def list_limits_below_one_raise(a: Adapters) -> None:
    seed(a)
    for limit in (0, -1):
        with pytest.raises(ValueError, match="limit"):
            a.feedback.list_for_tenant(TENANT_A.id, limit=limit)
        with pytest.raises(ValueError, match="limit"):
            a.queue.list_by_status(EventStatus.PENDING, limit=limit)


def disabled_sources_leave_list_enabled(a: Adapters) -> None:
    seed(a)
    a.sources.set_enabled(SOURCE_A2.id, TENANT_A.id, False)
    assert a.sources.list_enabled(SourceMode.PULL) == []
    assert [s.enabled for s in a.sources.list_for_tenant(TENANT_A.id)] == [True, False]
    with pytest.raises(NotFoundError):
        a.sources.set_enabled(SOURCE_A2.id, TENANT_B.id, True)
    a.sources.set_enabled(SOURCE_A2.id, TENANT_A.id, True)
    assert a.sources.list_enabled(SourceMode.PULL) == [SOURCE_A2]


def get_record_is_tenant_scoped(a: Adapters) -> None:
    seed(a)
    stored = record(SOURCE_A1, "r1", a.clock.now())
    a.feedback.upsert(stored)
    assert a.feedback.get(stored.id, TENANT_A.id) == stored
    assert a.feedback.get(stored.id, TENANT_B.id) is None
    assert a.feedback.get("missing", TENANT_A.id) is None


STORE_CASES: list[Case] = [
    same_external_id_in_two_sources_is_two_rows,
    tenants_are_isolated,
    filters_and_lookups_match,
    duplicates_and_unknown_ids_raise,
    list_limits_below_one_raise,
    disabled_sources_leave_list_enabled,
    get_record_is_tenant_scoped,
]
