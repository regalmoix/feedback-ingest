from sqlite3 import Connection as SqliteConnection

from sqlalchemy import Connection, Engine, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry
from sqlalchemy.schema import CreateColumn

from feedback_ingest.adapters.sqlalchemy.tables import Base


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


def sessions(engine: Engine) -> tuple[sessionmaker[Session], sessionmaker[Session]]:
    read_only = engine.execution_options(read_only=True)
    return (
        sessionmaker(engine, expire_on_commit=False),
        sessionmaker(read_only, expire_on_commit=False),
    )


# ponytail: create_all never alters an existing table; fail fast here until there are migrations
def assert_schema_matches(engine: Engine) -> None:
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        present = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in present:
                ddl = CreateColumn(column).compile(dialect=engine.dialect)
                msg = (
                    f"schema out of date: {table.name}.{column.name} missing; delete the db file "
                    f"or run ALTER TABLE {table.name} ADD COLUMN {ddl}"
                )
                raise RuntimeError(msg)
