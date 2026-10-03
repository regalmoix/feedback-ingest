import httpx
import pytest

from feedback_ingest.adapters.http.httpx_client import HttpxClient
from feedback_ingest.domain.errors import PermanentError, TransientError


def _client(status: int, body: object = None) -> HttpxClient:
    return HttpxClient(httpx.MockTransport(lambda _: httpx.Response(status, json=body)))


def test_returns_json_object_sends_params_and_does_not_follow_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "http://169.254.169.254/"})
        return httpx.Response(200, json={"q": request.url.params.get_list("q")})

    client = HttpxClient(httpx.MockTransport(handler))
    params = [("q", "x"), ("q", "y")]
    assert client.get_json("https://example.test/new", params) == {"q": ["x", "y"]}
    with pytest.raises(PermanentError, match="301 from"):
        client.get_json("https://example.test/old")


def test_proxy_settings_in_the_environment_are_ignored() -> None:
    client = HttpxClient()
    assert client._client.trust_env is False  # noqa: SLF001  env proxies would bypass the SSRF check
    client.close()


def test_a_response_over_the_size_cap_is_transient() -> None:
    big = HttpxClient(httpx.MockTransport(lambda _: httpx.Response(200, json=["x" * 20])), 20)
    with pytest.raises(TransientError, match="response too large"):
        big.get_json("https://example.test")


@pytest.mark.parametrize(
    ("url", "params", "sent"),
    [
        ("https://example.test/t?ids%5B%5D=1&ids%5B%5D=2", [], ""),
        ("https://example.test/t?ids%5B%5D=1", [("page", "2")], "&page=2"),
    ],
)
def test_query_in_url_is_kept(url: str, params: list[tuple[str, str]], sent: str) -> None:
    client = HttpxClient(httpx.MockTransport(lambda r: httpx.Response(200, json={"u": str(r.url)})))
    assert client.get_json(url, params) == {"u": url + sent}


@pytest.mark.parametrize("status", [408, 429, 500, 503])
def test_retryable_statuses_are_transient_and_keep_the_body_out(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(TransientError, match=f"{status} from") as raised:
        _client(status, {"detail": "slow down"}).get_json("https://example.test")
    assert "slow down" not in str(raised.value)
    assert caplog.records == []  # the caller logs the raised message with its ids


def test_client_errors_and_non_objects_are_transform_errors() -> None:
    for status in (304, 404):
        with pytest.raises(PermanentError, match=str(status)):
            _client(status).get_json("https://example.test")
    with pytest.raises(PermanentError):
        _client(200, [1, 2]).get_json("https://example.test")
    with pytest.raises(PermanentError):
        _client(200, {}).get_json("http://[::1")


@pytest.mark.parametrize("url", ["example.test/x", "ftp://example.test/x"])
def test_url_without_http_scheme_is_a_transform_error(url: str) -> None:
    with pytest.raises(PermanentError):
        HttpxClient().get_json(url)


@pytest.mark.parametrize("body", ["<html>", "[" * 100_000])
def test_invalid_json_is_transient(body: str) -> None:
    client = HttpxClient(httpx.MockTransport(lambda _: httpx.Response(200, text=body)))
    with pytest.raises(TransientError, match="invalid JSON") as raised:
        client.get_json("https://user:hunter2@example.test")
    assert "hunter2" not in str(raised.value)


@pytest.mark.parametrize("error", [httpx.ConnectError, httpx.TooManyRedirects])
def test_request_failures_are_transient(error: type[httpx.RequestError]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise error(str(request.url), request=request)

    with pytest.raises(TransientError):
        HttpxClient(httpx.MockTransport(handler)).get_json("https://example.test")


def test_request_failures_keep_upstream_bytes_out_of_the_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        msg = "illegal header line: bytearray(b'secret-banner')"
        raise httpx.RemoteProtocolError(msg, request=request)

    client = HttpxClient(httpx.MockTransport(handler))
    with pytest.raises(
        TransientError, match=r"RemoteProtocolError from https://example\.test/x"
    ) as raised:
        client.get_json("https://example.test/x")
    assert "secret-banner" not in str(raised.value)


def test_error_messages_drop_credentials_from_the_url() -> None:
    with pytest.raises(PermanentError) as raised:
        _client(404).get_json("https://user:hunter2@example.test/x")
    assert "hunter2" not in str(raised.value)
    assert "https://example.test/x" in str(raised.value)
