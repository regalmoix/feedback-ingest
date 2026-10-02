import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from contract import SOURCE_A1, TENANT_A, TENANT_B, Adapters, Case, event, record, seed
from contract_queue import QUEUE_CASES
from contract_queue_fencing import FENCING_CASES
from contract_stores import STORE_CASES
from contract_upsert import UPSERT_CASES
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.adapters.sqlalchemy.db import make_engine
from feedback_ingest.adapters.sqlalchemy.feedback_store import SqlFeedbackStore
from feedback_ingest.adapters.sqlalchemy.raw_event_queue import SqlRawEventQueue
from feedback_ingest.adapters.sqlalchemy.stores import SqlSourceStore, SqlTenantStore

CASES = STORE_CASES + UPSERT_CASES + QUEUE_CASES + FENCING_CASES


def _adapters(engine: Engine, clock: FixedClock) -> Adapters:
    return Adapters(
        SqlTenantStore(engine),
        SqlSourceStore(engine),
        SqlFeedbackStore(engine),
        SqlRawEventQueue(engine),
        clock,
    )


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_contract(case: Case, engine: Engine, clock: FixedClock) -> None:
    case(_adapters(engine, clock))


def test_wal_is_on(engine: Engine) -> None:
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_rows_must_belong_to_their_sources_tenant(engine: Engine, clock: FixedClock) -> None:
    a = _adapters(engine, clock)
    seed(a)
    with pytest.raises(IntegrityError):
        a.feedback.upsert(record(SOURCE_A1, "r1", clock.now(), tenant_id=TENANT_B.id))
    with pytest.raises(IntegrityError):
        a.queue.enqueue(
            event(SOURCE_A1, "e1", clock.now()).model_copy(update={"tenant_id": TENANT_B.id})
        )


def test_reads_do_not_wait_for_the_write_lock(engine: Engine, clock: FixedClock) -> None:
    a = _adapters(engine, clock)
    seed(a)
    with engine.begin():  # holds BEGIN IMMEDIATE
        start = time.monotonic()
        a.queue.counts()
        a.feedback.list_for_tenant(TENANT_A.id)
        assert time.monotonic() - start < 1


def test_concurrent_claims_are_disjoint(engine: Engine, clock: FixedClock) -> None:
    a = _adapters(engine, clock)
    seed(a)
    now = clock.now()
    for n in range(40):
        a.queue.enqueue(event(SOURCE_A1, f"e{n}", now))
    workers = 4
    barrier = threading.Barrier(workers)

    def drain() -> list[str]:
        own = make_engine(str(engine.url))
        own.connect().close()
        queue = SqlRawEventQueue(own)
        barrier.wait()
        claimed: list[str] = []
        while batch := queue.claim(now, lease_seconds=60, limit=3):
            claimed += [e.id for e in batch]
        own.dispose()
        return claimed

    with ThreadPoolExecutor(workers) as pool:
        results = [f.result() for f in [pool.submit(drain) for _ in range(workers)]]
    claimed = [event_id for result in results for event_id in result]
    assert len(claimed) == len(set(claimed)) == 40
