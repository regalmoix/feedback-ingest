from collections.abc import Mapping
from typing import Any, Protocol


class _Response(Protocol):
    @property
    def is_success(self) -> bool: ...
    @property
    def status_code(self) -> int: ...
    @property
    def text(self) -> str: ...
    def json(self) -> Any: ...  # noqa: ANN401  JSON from our own API


class Client(Protocol):
    def post(
        self, url: str, *, json: object = None, headers: Mapping[str, str] | None = None
    ) -> _Response: ...


TENANTS = ("acme", "globex")
DISCOURSE = {
    "base_url": "https://meta.discourse.org",
    "start_after": "2021-01-01",
    "window_days": "4",
}


def _post(client: Client, url: str, body: object, headers: Mapping[str, str]) -> dict[str, Any]:
    response = client.post(url, json=body, headers=headers)
    if not response.is_success:
        msg = f"POST {url}: {response.status_code} {response.text}"
        raise RuntimeError(msg)
    created: dict[str, Any] = response.json()
    return created


def create_tenant(client: Client, bootstrap_token: str, name: str) -> dict[str, str]:
    return _post(client, "/admin/tenants", {"name": name}, {"X-Bootstrap-Token": bootstrap_token})


def create_source(
    client: Client, api_key: str, type_: str, name: str, config: dict[str, str] | None = None
) -> dict[str, Any]:
    body = {"type": type_, "name": name, "mode": "pull" if config else "push"}
    return _post(client, "/v1/sources", body | {"config": config or {}}, {"X-API-Key": api_key})


def seed_tenant(client: Client, bootstrap_token: str, name: str) -> dict[str, Any]:
    tenant = create_tenant(client, bootstrap_token, name)
    wanted = [
        ("discourse", f"{name}-forum", DISCOURSE),
        ("playstore", f"{name}-android", None),
        ("playstore", f"{name}-ios-wrapper", None),
        ("twitter", f"{name}-twitter", None),
        ("intercom", f"{name}-intercom", None),
    ]
    sources = {
        source_name: create_source(client, tenant["api_key"], type_, source_name, config)
        for type_, source_name, config in wanted
    }
    return tenant | {"sources": sources}


def seed(client: Client, bootstrap_token: str) -> dict[str, dict[str, Any]]:
    return {name: seed_tenant(client, bootstrap_token, name) for name in TENANTS}
