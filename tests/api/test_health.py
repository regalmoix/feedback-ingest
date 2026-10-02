from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from helpers import app_state, client_for, wait_until
from sqlalchemy import text

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.adapters.sqlalchemy.db import make_engine
from feedback_ingest.api.deps import Adapters
from feedback_ingest.config import Settings
from feedback_ingest.domain.models import RawEvent
from feedback_ingest.main import create_app


def test_ok_without_auth_when_the_worker_is_disabled(app_client: TestClient) -> None:
    response = app_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert (body["worker_enabled"], body["worker_alive"]) == (False, False)
    assert (body["scheduler_enabled"], body["scheduler_alive"]) == (False, False)
    assert body["queue"]["pending"] == 0


def test_degraded_when_the_enabled_worker_thread_is_dead(adapters: Adapters) -> None:
    with client_for(adapters, worker_enabled=True) as client:
        assert client.get("/health").json()["worker_alive"] is True
        app_state(client).worker.stop()
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_degraded_without_a_completed_pass_in_the_window_then_recovers(
    adapters: Adapters, clock: FixedClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object) -> list[RawEvent]:
        msg = "database is locked"
        raise RuntimeError(msg)

    monkeypatch.setattr(adapters.queue, "claim", broken)
    with client_for(adapters, worker_enabled=True, worker_poll_seconds=0.05) as client:
        assert client.get("/health").status_code == 200
        clock.advance(11)
        response = client.get("/health")
        assert (response.status_code, response.json()["worker_alive"]) == (503, True)
        monkeypatch.undo()
        wait_until(lambda: client.get("/health").status_code == 200)


def test_degraded_when_the_enabled_scheduler_thread_is_dead(adapters: Adapters) -> None:
    with client_for(adapters, scheduler_enabled=True) as client:
        assert client.get("/health").json()["scheduler_alive"] is True
        app_state(client).scheduler.stop()
        response = client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert (body["scheduler_enabled"], body["scheduler_alive"]) == (True, False)


def test_degraded_listing_sources_whose_last_scheduled_sync_failed(
    app_client: TestClient,
) -> None:
    app_state(app_client).scheduler.last_errors = {"src-forum": "503 from x"}
    response = app_client.get("/health")
    assert response.status_code == 503
    assert (response.json()["status"], response.json()["failing_sources"]) == (
        "degraded",
        ["src-forum"],
    )


def test_lifespan_exit_stops_the_worker(adapters: Adapters) -> None:
    with client_for(adapters, worker_enabled=True) as client:
        worker = app_state(client).worker
        assert worker.alive
    assert not worker.alive


def _sql_settings(tmp_path: Path) -> Settings:
    database_url = f"sqlite:///{tmp_path / 'app.db'}"
    return Settings(database_url=database_url, worker_enabled=False, scheduler_enabled=False)


def test_lifespan_closes_the_http_client_it_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[HttpxClient] = []
    close = HttpxClient.close

    def spy(self: HttpxClient) -> None:
        closed.append(self)
        close(self)

    monkeypatch.setattr(HttpxClient, "close", spy)
    with TestClient(create_app(_sql_settings(tmp_path))):
        assert closed == []
    assert len(closed) == 1


def test_startup_stops_on_a_table_missing_a_column(tmp_path: Path) -> None:
    settings = _sql_settings(tmp_path)
    engine = make_engine(settings.database_url)
    with engine.begin() as conn:  # the sources table as it was before `enabled` existed
        conn.execute(
            text(
                "CREATE TABLE sources (id TEXT PRIMARY KEY, tenant_id TEXT, type TEXT, name TEXT,"
                " mode TEXT, config JSON, webhook_secret TEXT, cursor TEXT)"
            )
        )
    engine.dispose()
    missing = r"sources\.enabled missing.*ADD COLUMN enabled"
    with pytest.raises(RuntimeError, match=missing), TestClient(create_app(settings)):
        pass
