import logging
from http import HTTPStatus
from typing import Any

import httpx

from feedback_ingest.domain.errors import TransformError, TransientError

log = logging.getLogger(__name__)
_RETRYABLE_4XX = (HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.TOO_MANY_REQUESTS)


class HttpxClient:
    # ponytail: redirects are followed without re-checking the target, so a public base_url can
    # redirect to an internal host; validate each hop if tenants are untrusted
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(timeout=10, transport=transport, follow_redirects=True)

    def close(self) -> None:
        self._client.close()

    def get_json(self, url: str, params: dict[str, str]) -> dict[str, Any]:
        try:
            response = self._client.get(httpx.URL(url).copy_merge_params(params))
        except (httpx.InvalidURL, httpx.UnsupportedProtocol) as exc:
            raise TransformError(str(exc)) from exc
        except httpx.RequestError as exc:
            raise TransientError(str(exc)) from exc
        status = response.status_code
        if status >= HTTPStatus.MULTIPLE_CHOICES:
            log.warning("%s from %s: %s", status, _safe(url), response.text[:200])
            retryable = status in _RETRYABLE_4XX or status >= HTTPStatus.INTERNAL_SERVER_ERROR
            kind = TransientError if retryable else TransformError
            msg = f"{status} from {_safe(url)}"
            raise kind(msg)
        try:
            data = response.json()
        except (ValueError, RecursionError) as exc:
            log.warning("invalid JSON from %s: %s", _safe(url), response.text[:200])
            msg = f"invalid JSON from {_safe(url)}"
            raise TransientError(msg) from exc
        if not isinstance(data, dict):
            msg = f"expected a JSON object from {_safe(url)}"
            raise TransformError(msg)
        return data


def _safe(url: str) -> httpx.URL:
    return httpx.URL(url).copy_with(username=None, password=None)
