from feedback_ingest.utils.hashing import payload_hash
from feedback_ingest.utils.signing import sign, verify


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
