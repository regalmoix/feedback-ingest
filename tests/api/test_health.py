from fastapi.testclient import TestClient

from api.conftest import app_state
from feedback_ingest.api.deps import Adapters
from feedback_ingest.config import Settings
from feedback_ingest.main import create_app


def test_ok_without_auth_when_the_worker_is_disabled(app_client: TestClient) -> None:
    response = app_client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert (body["worker_enabled"], body["worker_alive"]) == (False, False)
    assert body["queue"]["pending"] == 0


def test_degraded_when_the_enabled_worker_thread_is_dead(adapters: Adapters) -> None:
    with TestClient(create_app(Settings(worker_enabled=True), adapters=adapters)) as client:
        assert client.get("/health").json()["worker_alive"] is True
        app_state(client).worker.stop()
        response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"
