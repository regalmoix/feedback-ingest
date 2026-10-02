from sqlite3 import Connection as SqliteConnection

from sqlalchemy import Connection, Engine, create_engine, event
from sqlalchemy.pool import ConnectionPoolEntry


def make_engine(database_url: str) -> Engine:
    engine = create_engine(database_url, hide_parameters=True)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _on_connect(conn: SqliteConnection, _record: ConnectionPoolEntry) -> None:
            conn.isolation_level = None  # let SQLAlchemy emit BEGIN itself (pysqlite recipe)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(engine, "begin")
        def _on_begin(conn: Connection) -> None:
            # reads skip the write lock; writes take it up front instead of failing on upgrade
            read_only = conn.get_execution_options().get("read_only")
            conn.exec_driver_sql("BEGIN" if read_only else "BEGIN IMMEDIATE")

    return engine
