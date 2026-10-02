from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    import httpx
    import httpx2

    type Client = httpx.Client | httpx2.Client

DISCOURSE = {
    "base_url": "https://meta.discourse.org",
    "start_after": "2021-01-01",
    "window_days": "4",
}
# synthetic demo tenants (a consumer app, a B2B SaaS): (type, source name, pull config)
TENANTS: dict[str, list[tuple[str, str, dict[str, str] | None]]] = {
    "lumenote": [
        ("discourse", "lumenote-community", DISCOURSE),
        ("playstore", "lumenote-android", None),
        ("playstore", "lumenote-android-beta", None),
        ("custom", "lumenote-surveys", None),
    ],
    "brightwave": [
        ("intercom", "brightwave-support", None),
        ("twitter", "brightwave-x", None),
        ("custom", "brightwave-nps", None),
    ],
}


def _post(client: Client, url: str, body: object, headers: Mapping[str, str]) -> dict[str, Any]:
    response = client.post(url, json=body, headers=headers)
    if not response.is_success:
        msg = f"POST {url}: {response.status_code} {response.text}"
        raise RuntimeError(msg)
    try:
        created: dict[str, Any] = response.json()
    except ValueError as exc:
        msg = f"POST {url}: {response.status_code} but not JSON: {response.text[:200]}"
        raise RuntimeError(msg) from exc
    return created


def create_tenant(client: Client, bootstrap_token: str, name: str) -> dict[str, Any]:
    return _post(client, "/admin/tenants", {"name": name}, {"X-Bootstrap-Token": bootstrap_token})


def create_source(
    client: Client, api_key: str, type_: str, name: str, config: dict[str, str] | None = None
) -> dict[str, Any]:
    body = {"type": type_, "name": name, "mode": "pull" if config else "push"}
    return _post(client, "/v1/sources", body | {"config": config or {}}, {"X-API-Key": api_key})


def seed_tenant(
    client: Client,
    bootstrap_token: str,
    name: str,
    save: Callable[[dict[str, Any]], object] = lambda _: None,
) -> dict[str, Any]:
    tenant = create_tenant(client, bootstrap_token, name)
    save(tenant)  # the api key is kept even if a source below fails
    tenant["sources"] = {
        source_name: create_source(client, tenant["api_key"], type_, source_name, config)
        for type_, source_name, config in TENANTS[name]
    }
    return tenant
