import httpx
import pytest

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.domain.errors import TransformError, TransientError


def _client(status: int, body: object = None) -> HttpxClient:
    return HttpxClient(httpx.MockTransport(lambda _: httpx.Response(status, json=body)))


def test_returns_json_object_sends_params_and_follows_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/new?q=x"})
        return httpx.Response(200, json={"q": request.url.params["q"]})

    client = HttpxClient(httpx.MockTransport(handler))
    assert client.get_json("https://example.test/old", {"q": "x"}) == {"q": "x"}


def test_query_in_url_is_kept_when_params_are_empty() -> None:
    client = HttpxClient(httpx.MockTransport(lambda r: httpx.Response(200, json={"u": str(r.url)})))
    url = "https://example.test/t?ids%5B%5D=1&ids%5B%5D=2"
    assert client.get_json(url, {}) == {"u": url}


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_retryable_statuses_are_transient(status: int) -> None:
    with pytest.raises(TransientError, match=f"{status}.*slow down"):
        _client(status, {"detail": "slow down"}).get_json("https://example.test", {})


def test_client_errors_and_non_objects_are_transform_errors() -> None:
    for status in (304, 404):
        with pytest.raises(TransformError, match=str(status)):
            _client(status).get_json("https://example.test", {})
    with pytest.raises(TransformError):
        _client(200, [1, 2]).get_json("https://example.test", {})
    with pytest.raises(TransformError):
        _client(200, {}).get_json("http://[::1", {})


@pytest.mark.parametrize("url", ["example.test/x", "ftp://example.test/x"])
def test_url_without_http_scheme_is_a_transform_error(url: str) -> None:
    with pytest.raises(TransformError):
        HttpxClient().get_json(url, {})


@pytest.mark.parametrize("body", ["<html>", "[" * 100_000])
def test_invalid_json_is_transient(body: str) -> None:
    client = HttpxClient(httpx.MockTransport(lambda _: httpx.Response(200, text=body)))
    with pytest.raises(TransientError, match="invalid JSON"):
        client.get_json("https://example.test", {})


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.TooManyRedirects])
def test_request_failures_are_transient(error: type[httpx.RequestError]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error(str(request.url), request=request)

    with pytest.raises(TransientError):
        HttpxClient(httpx.MockTransport(handler)).get_json("https://example.test", {})
