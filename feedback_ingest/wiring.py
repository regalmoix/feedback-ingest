from collections.abc import Iterator
from contextlib import contextmanager

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.adapters.sqlalchemy.db import assert_schema_matches, make_engine
from feedback_ingest.adapters.sqlalchemy.feedback_store import SqlFeedbackStore
from feedback_ingest.adapters.sqlalchemy.raw_event_queue import SqlRawEventQueue
from feedback_ingest.adapters.sqlalchemy.stores import SqlSourceStore, SqlTenantStore
from feedback_ingest.adapters.sqlalchemy.tables import Base
from feedback_ingest.api.deps import Adapters
from feedback_ingest.utils.time import SystemClock


@contextmanager
def sql_adapters(database_url: str) -> Iterator[Adapters]:
    engine = make_engine(database_url)
    http = HttpxClient()
    try:
        Base.metadata.create_all(engine)
        assert_schema_matches(engine)
        yield Adapters(
            tenants=SqlTenantStore(engine),
            sources=SqlSourceStore(engine),
            feedback=SqlFeedbackStore(engine),
            queue=SqlRawEventQueue(engine),
            http=http,
            clock=SystemClock(),
        )
    finally:
        http.close()
        engine.dispose()
