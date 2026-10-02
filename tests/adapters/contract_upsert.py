from datetime import timedelta

from contract import SOURCE_A1, TENANT_A, Case, record, seed

from feedback_ingest.api.deps import Adapters
from feedback_ingest.domain.enums import UpsertOutcome


def upsert_keeps_row_id_and_store_owned_fields(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    first = record(SOURCE_A1, "r1", now)
    assert a.feedback.upsert(first) == UpsertOutcome.INSERTED
    assert a.feedback.list_for_tenant(TENANT_A.id) == [first]
    later = now + timedelta(minutes=1)
    edit = record(
        SOURCE_A1, "r1", now + timedelta(seconds=1), source_updated_at=later, ingested_at=later
    )
    assert a.feedback.upsert(edit) == UpsertOutcome.UPDATED
    kept = {"id": first.id, "source_created_at": now, "ingested_at": now}
    assert a.feedback.list_for_tenant(TENANT_A.id) == [edit.model_copy(update=kept)]


def older_update_is_skipped(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.feedback.upsert(
        record(SOURCE_A1, "r1", now, source_updated_at=now + timedelta(minutes=10), text="new")
    )
    older = record(SOURCE_A1, "r1", now, source_updated_at=now + timedelta(minutes=5), text="old")
    assert a.feedback.upsert(older) == UpsertOutcome.SKIPPED_OLDER
    assert [r.text for r in a.feedback.list_for_tenant(TENANT_A.id)] == ["new"]


def missing_updated_at_falls_back_to_created_at(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.feedback.upsert(record(SOURCE_A1, "r1", now, text="first"))
    newer = record(SOURCE_A1, "r1", now + timedelta(seconds=1), text="second")
    assert a.feedback.upsert(newer) == UpsertOutcome.UPDATED
    stale = record(SOURCE_A1, "r1", now - timedelta(seconds=1), text="stale")
    assert a.feedback.upsert(stale) == UpsertOutcome.SKIPPED_OLDER
    assert [r.text for r in a.feedback.list_for_tenant(TENANT_A.id)] == ["second"]


def tombstone_survives_newer_edit(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    deleted, edited = now + timedelta(minutes=1), now + timedelta(minutes=2)
    a.feedback.upsert(record(SOURCE_A1, "r1", now))
    a.feedback.upsert(record(SOURCE_A1, "r1", now, source_updated_at=deleted, deleted_at=deleted))
    edit = record(SOURCE_A1, "r1", now, source_updated_at=edited, text="edited")
    assert a.feedback.upsert(edit) == UpsertOutcome.UPDATED
    assert a.feedback.list_for_tenant(TENANT_A.id) == []
    [stored] = a.feedback.list_for_tenant(TENANT_A.id, include_deleted=True)
    assert (stored.text, stored.deleted_at) == ("edited", deleted)


def older_tombstone_still_deletes(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    deleted = now + timedelta(minutes=1)
    a.feedback.upsert(record(SOURCE_A1, "r1", now))
    edited = now + timedelta(minutes=5)
    a.feedback.upsert(record(SOURCE_A1, "r1", now, source_updated_at=edited, text="edited"))
    tombstone = record(SOURCE_A1, "r1", now, deleted_at=deleted)
    assert a.feedback.upsert(tombstone) == UpsertOutcome.UPDATED
    assert a.feedback.list_for_tenant(TENANT_A.id) == []
    [stored] = a.feedback.list_for_tenant(TENANT_A.id, include_deleted=True)
    assert (stored.text, stored.deleted_at) == ("edited", deleted)


def version_advances_without_updated_at(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.feedback.upsert(record(SOURCE_A1, "r1", now, text="v1"))
    v3 = record(SOURCE_A1, "r1", now + timedelta(hours=3), text="v3")
    assert a.feedback.upsert(v3) == UpsertOutcome.UPDATED
    v2 = record(SOURCE_A1, "r1", now + timedelta(hours=2), text="v2")
    assert a.feedback.upsert(v2) == UpsertOutcome.SKIPPED_OLDER
    assert [r.text for r in a.feedback.list_for_tenant(TENANT_A.id)] == ["v3"]


def same_version_from_a_newer_connector_replaces_the_row(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    a.feedback.upsert(record(SOURCE_A1, "r1", now, text="old"))
    reprocessed = record(SOURCE_A1, "r1", now, text="new", connector_version=2)
    assert a.feedback.upsert(reprocessed) == UpsertOutcome.UPDATED
    [stored] = a.feedback.list_for_tenant(TENANT_A.id)
    assert (stored.text, stored.connector_version) == ("new", 2)


def an_older_tombstone_does_not_move_an_existing_one(a: Adapters) -> None:
    seed(a)
    now = a.clock.now()
    first_delete = now + timedelta(minutes=10)
    a.feedback.upsert(record(SOURCE_A1, "r1", now))
    a.feedback.upsert(
        record(SOURCE_A1, "r1", now, source_updated_at=first_delete, deleted_at=first_delete)
    )
    late = record(SOURCE_A1, "r1", now, deleted_at=now + timedelta(minutes=5))
    assert a.feedback.upsert(late) == UpsertOutcome.SKIPPED_OLDER
    [stored] = a.feedback.list_for_tenant(TENANT_A.id, include_deleted=True)
    assert stored.deleted_at == first_delete


UPSERT_CASES: list[Case] = [
    upsert_keeps_row_id_and_store_owned_fields,
    older_update_is_skipped,
    missing_updated_at_falls_back_to_created_at,
    tombstone_survives_newer_edit,
    older_tombstone_still_deletes,
    version_advances_without_updated_at,
    same_version_from_a_newer_connector_replaces_the_row,
    an_older_tombstone_does_not_move_an_existing_one,
]
