import time
from datetime import UTC, datetime, timedelta

import pytest

from feedback_ingest.utils.hashing import payload_hash, sha256_text
from feedback_ingest.utils.signing import sign, verify
from feedback_ingest.utils.time import SystemClock


def test_payload_hash_ignores_key_order() -> None:
    assert payload_hash({"a": 1, "b": {"c": 2, "d": 3}}) == payload_hash(
        {"b": {"d": 3, "c": 2}, "a": 1}
    )
    assert payload_hash({"a": 1}) != payload_hash({"a": 2})


def test_verify_rejects_tampered_body_wrong_secret_and_bad_signatures() -> None:
    body = b'{"id": 1}'
    signature = sign("secret", body)
    assert verify("secret", body, signature)
    assert not verify("secret", b'{"id": 2}', signature)
    assert not verify("other", body, signature)
    assert not verify("", body, sign("", body))
    assert not verify("secret", body, "")
    assert not verify("secret", body, "é" * 64)
    assert not verify("secret", body, "\ud800" * 64)


def test_hmac_matches_rfc_4231_case_2() -> None:
    expected = "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
    assert sign("Jefe", b"what do ya want for nothing?") == expected
    assert verify("Jefe", b"what do ya want for nothing?", expected)


def test_stored_hash_formats_are_pinned() -> None:  # stored api key hashes and event ids must match
    assert sha256_text("key-tenant-a") == (
        "751b22fa5c80cbdf9a40bebbf8d9c4d36e81973568f77f6d97150bc840c4b20a"
    )
    assert payload_hash({"b": 1, "a": [1, {"d": None, "c": "é"}]}) == (
        "8fda00cb5896d2d8dd26adb432bce9638f9eb1823d13808556c8ec5c07bd89a1"
    )


def test_system_clock_is_naive_utc_on_a_non_utc_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "XST-5:30")  # POSIX form, needs no tz database
    time.tzset()
    try:
        now = SystemClock().now()
    finally:
        monkeypatch.undo()
        time.tzset()
    assert now.tzinfo is None
    assert abs(now - datetime.now(UTC).replace(tzinfo=None)) < timedelta(seconds=5)
