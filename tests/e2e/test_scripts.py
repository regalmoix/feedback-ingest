import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from helpers import SECRET, TOKEN, client_for

from feedback_ingest.api.deps import Adapters
from feedback_ingest.utils.signing import sign
from scripts import seed
from scripts import sign as sign_script
from scripts.seed_lib import create_tenant, seed_tenant


def _fake_api(
    sources_status: int, tenant_body: str = '{"id": "t1", "name": "acme"}'
) -> httpx.Client:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/admin/tenants":
            return httpx.Response(201, text=tenant_body)
        return httpx.Response(sources_status, text="boom")

    return httpx.Client(base_url="http://api.test", transport=httpx.MockTransport(handle))


def test_the_tenant_is_saved_before_its_sources_are_created() -> None:
    saved: list[dict[str, Any]] = []
    api = _fake_api(500, '{"id": "t1", "name": "acme", "api_key": "k"}')
    with api, pytest.raises(RuntimeError, match="POST /v1/sources: 500 boom"):
        seed_tenant(api, TOKEN, "acme", saved.append)
    assert saved == [{"id": "t1", "name": "acme", "api_key": "k"}]


def test_a_2xx_that_is_not_json_names_the_status_and_the_body() -> None:
    api = _fake_api(500, "<html>proxy login</html>")
    with api, pytest.raises(RuntimeError, match=r"201 but not JSON: <html>proxy login"):
        create_tenant(api, TOKEN, "acme")


def test_seed_writes_a_private_file_and_prints_no_secrets(
    adapters: Adapters,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FI_BOOTSTRAP_TOKEN", TOKEN)
    test_client = client_for(adapters, bootstrap_token=TOKEN)
    monkeypatch.setattr(httpx, "Client", lambda **_: test_client)
    seed.main()
    seeded = json.loads(Path(".seed.json").read_text())
    assert Path(".seed.json").stat().st_mode & 0o777 == 0o600
    out = capsys.readouterr().out
    assert seeded["acme"]["api_key"] not in out
    assert seeded["acme"]["sources"]["acme-android"]["webhook_secret"] not in out


def test_seed_and_sign_need_their_secret_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    body = tmp_path / "body.json"
    body.write_bytes(b'{"id": 1}')
    monkeypatch.setattr("sys.argv", ["sign.py", str(body)])
    with pytest.raises(SystemExit, match="set FI_SIGN_SECRET"):
        sign_script.main()
    with pytest.raises(SystemExit, match="set FI_BOOTSTRAP_TOKEN"):
        seed.main()
    monkeypatch.setenv("FI_SIGN_SECRET", SECRET)
    sign_script.main()
    assert capsys.readouterr().out.strip() == sign(SECRET, b'{"id": 1}')
