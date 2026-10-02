from collections.abc import Mapping
from typing import Any, Protocol


class _Response(Protocol):
    def json(self) -> Any: ...  # noqa: ANN401  JSON from our own API
    def raise_for_status(self) -> object: ...


class Client(Protocol):
    def post(
        self, url: str, *, json: object = None, headers: Mapping[str, str] | None = None
    ) -> _Response: ...


TENANTS = ("acme", "globex")
DISCOURSE = {
    "base_url": "https://meta.discourse.org",
    "start_after": "2021-01-01",
    "until": "2021-01-05",
    "window_days": "4",
}


def create_tenant(client: Client, bootstrap_token: str, name: str) -> dict[str, str]:
    response = client.post(
        "/admin/tenants", json={"name": name}, headers={"X-Bootstrap-Token": bootstrap_token}
    )
    response.raise_for_status()
    tenant: dict[str, str] = response.json()
    return tenant


def create_source(
    client: Client, api_key: str, type_: str, name: str, config: dict[str, str] | None = None
) -> dict[str, Any]:
    body = {"type": type_, "name": name, "mode": "pull" if config else "push"}
    response = client.post(
        "/v1/sources", json=body | {"config": config or {}}, headers={"X-API-Key": api_key}
    )
    response.raise_for_status()
    source: dict[str, Any] = response.json()
    return source


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
