import asyncio
import logging
from collections.abc import Iterator, Mapping

import pytest
from fastapi.testclient import TestClient
from helpers import MINE, SECRET, client_for, push
from sqlalchemy import exc as sa_exc

from feedback_ingest.api.body_limit import MAX_BODY_BYTES
from feedback_ingest.api.deps import Adapters
from feedback_ingest.connectors.registry import CONNECTORS
from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.models import RawEvent, Source
from feedback_ingest.main import OneLineFormatter
from feedback_ingest.services.scheduler import SchedulerService
from feedback_ingest.services.worker import WorkerService
from feedback_ingest.utils.signing import sign

DOWN = sa_exc.OperationalError("SELECT", {}, Exception("disk I/O error"))


def test_a_body_over_the_limit_is_413_declared_or_streamed(
    app_client: TestClient, source_a: Source
) -> None:
    big = b"{" + b" " * MAX_BODY_BYTES + b"}"
    assert push(app_client, source_a.id, big).status_code == 413

    def chunks() -> Iterator[bytes]:  # no Content-Length: the cap counts what arrives
        yield big[: len(big) // 2]
        yield big[len(big) // 2 :]

    headers = {"X-Signature": sign(SECRET, big)}
    url = f"/v1/sources/{source_a.id}/events"
    assert app_client.post(url, content=chunks(), headers=headers).status_code == 413


def test_signature_check_runs_off_the_event_loop(
    app_client: TestClient, source_a: Source, monkeypatch: pytest.MonkeyPatch
) -> None:
    connector = CONNECTORS[SourceType.PLAYSTORE]
    verify = connector.verify_signature

    def off_loop(secret: str, body: bytes, headers: Mapping[str, str]) -> bool:
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return verify(secret, body, headers)

    monkeypatch.setattr(connector, "verify_signature", off_loop)
    assert push(app_client, source_a.id, b'{"reviewId": "r"}').status_code == 202


def test_json_nested_too_deep_to_store_is_400(app_client: TestClient, source_a: Source) -> None:
    deep = b'{"a":' * 300 + b"1" + b"}" * 300
    assert push(app_client, source_a.id, deep).status_code == 400


@pytest.mark.usefixtures("source_a")
def test_storage_down_logs_the_raw_event_id_from_the_path(
    app_client: TestClient,
    adapters: Adapters,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def down(_event_id: str) -> RawEvent:
        raise DOWN

    monkeypatch.setattr(adapters.queue, "get", down)
    assert app_client.get("/admin/raw-events/ev-1", headers=MINE).status_code == 503
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert (vars(record)["raw_event_id"], vars(record)["source_id"]) == ("ev-1", "-")


def test_log_lines_cannot_be_split_by_injected_newlines() -> None:
    record = logging.LogRecord("feedback_ingest", logging.INFO, "", 0, "a\r\nb %s", ("c\nd",), None)
    assert OneLineFormatter("%(message)s").format(record) == "a\\r\\nb c\\nd"


def test_a_failed_scheduler_start_still_stops_the_worker(
    adapters: Adapters, monkeypatch: pytest.MonkeyPatch
) -> None:
    stop, stopped = WorkerService.stop, []

    def boom(_self: SchedulerService) -> None:
        msg = "cannot start thread"
        raise RuntimeError(msg)

    def spy(self: WorkerService) -> None:
        stopped.append(self.alive)
        stop(self)

    monkeypatch.setattr(SchedulerService, "start", boom)
    monkeypatch.setattr(WorkerService, "stop", spy)
    with (
        pytest.raises(RuntimeError, match="cannot start thread"),
        client_for(adapters, worker_enabled=True, scheduler_enabled=True),
    ):
        pass
    assert stopped == [True]
