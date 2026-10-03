import json
from collections.abc import Sequence
from http import HTTPStatus
from typing import Any

import httpx

from feedback_ingest.domain.errors import PermanentError, TransientError
from feedback_ingest.ports.http import HttpClient

_RETRYABLE_4XX = (HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.TOO_MANY_REQUESTS)


class HttpxClient(HttpClient):
    # no redirects (a public base_url must not bounce us to an internal host), no env proxies
    def __init__(
        self, transport: httpx.BaseTransport | None = None, max_bytes: int = 2_000_000
    ) -> None:
        self._client = httpx.Client(
            timeout=10, transport=transport, follow_redirects=False, trust_env=False
        )
        self._max_bytes = max_bytes

    def close(self) -> None:
        self._client.close()

    def get_json(self, url: str, params: Sequence[tuple[str, str]] = ()) -> dict[str, Any]:
        try:
            target = httpx.URL(url).copy_merge_params(tuple(params))
            with self._client.stream("GET", target) as response:
                _raise_for_status(response.status_code, url)
                body = self._read(response)
        except (httpx.InvalidURL, httpx.UnsupportedProtocol) as exc:
            msg = f"{type(exc).__name__}: not a usable http(s) URL"  # _safe(url) would re-raise
            raise PermanentError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"{type(exc).__name__} from {_safe(url)}"
            raise TransientError(msg) from exc
        try:
            data = json.loads(body)
        except (ValueError, RecursionError) as exc:
            msg = f"invalid JSON from {_safe(url)}"
            raise TransientError(msg) from exc
        if not isinstance(data, dict):
            msg = f"expected a JSON object from {_safe(url)}"
            raise PermanentError(msg)
        return data

    def _read(self, response: httpx.Response) -> bytes:
        body = bytearray()
        for chunk in response.iter_bytes():
            body += chunk
            if len(body) > self._max_bytes:
                msg = f"response too large from {_safe(str(response.url))}"
                raise TransientError(msg)
        return bytes(body)


def _raise_for_status(status: int, url: str) -> None:
    if status < HTTPStatus.MULTIPLE_CHOICES:
        return
    retryable = status in _RETRYABLE_4XX or status >= HTTPStatus.INTERNAL_SERVER_ERROR
    kind = TransientError if retryable else PermanentError
    msg = f"{status} from {_safe(url)}"
    raise kind(msg)


def _safe(url: str) -> httpx.URL:
    return httpx.URL(url).copy_with(username=None, password=None)
