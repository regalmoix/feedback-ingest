from http import HTTPStatus
from typing import Any

import httpx

from feedback_ingest.domain.errors import TransformError, TransientError

_RETRYABLE_4XX = (HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.TOO_MANY_REQUESTS)


class HttpxClient:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(timeout=10, transport=transport, follow_redirects=True)

    def get_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            response = self._client.get(url, params=params)
        except httpx.InvalidURL as exc:
            raise TransformError(str(exc)) from exc
        except httpx.RequestError as exc:
            raise TransientError(str(exc)) from exc
        status = response.status_code
        if status >= HTTPStatus.MULTIPLE_CHOICES:
            retryable = status in _RETRYABLE_4XX or status >= HTTPStatus.INTERNAL_SERVER_ERROR
            kind = TransientError if retryable else TransformError
            msg = f"{status} from {url}: {response.text[:200]}"
            raise kind(msg)
        try:
            data = response.json()
        except (ValueError, RecursionError) as exc:
            msg = f"invalid JSON from {url}: {response.text[:200]}"
            raise TransientError(msg) from exc
        if not isinstance(data, dict):
            msg = f"expected a JSON object from {url}"
            raise TransformError(msg)
        return data
