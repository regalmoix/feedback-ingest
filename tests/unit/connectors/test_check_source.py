import pytest
from connector_fixtures import source

from feedback_ingest.connectors.registry import PULLERS, check_source
from feedback_ingest.domain.enums import SourceMode, SourceType


@pytest.mark.parametrize("source_type", sorted(set(SourceType) - PULLERS.keys()))
def test_pull_needs_a_puller(source_type: SourceType) -> None:
    with pytest.raises(ValueError, match="cannot pull"):
        check_source(source(source_type, SourceMode.PULL))


DISCOURSE = PULLERS[SourceType.DISCOURSE]


@pytest.mark.parametrize(
    ("mode", "key"),
    [(SourceMode.PULL, k) for k in DISCOURSE.required_config + DISCOURSE.pull_config]
    + [(SourceMode.PUSH, k) for k in DISCOURSE.required_config],
)
def test_every_required_config_key_is_checked(mode: SourceMode, key: str) -> None:
    configured = source(SourceType.DISCOURSE, mode)
    check_source(configured)
    missing = {k: v for k, v in configured.config.items() if k != key}
    with pytest.raises(ValueError, match=key):
        check_source(configured.model_copy(update={"config": missing}))


def test_push_does_not_need_pull_only_keys() -> None:
    push = source(SourceType.DISCOURSE)
    check_source(push.model_copy(update={"config": {"base_url": "https://forum.example.test"}}))


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("window_days", "0"),
        ("window_days", "-3"),
        ("window_days", "a week"),
        ("window_days", "32"),
        ("base_url", "forum.example.test"),
        ("base_url", "ftp://forum.example.test"),
        ("base_url", "https://user:pw@forum.example.test"),
        ("base_url", "https://:pw@forum.example.test"),
        ("base_url", "http://127.0.0.1"),
        ("base_url", "http://[::1]:8000"),
        ("base_url", "http://169.254.169.254/latest"),
        ("base_url", "http://10.0.0.5"),
        ("base_url", "https://localhost"),
        ("base_url", "https://metadata.google.internal"),
        ("base_url", "https://printer.local"),
        ("base_url", "https://"),
        ("base_url", "http:///path"),
        ("base_url", "http://[64:ff9b::7f00:1]"),
        ("base_url", "http://[64:ff9b::a9fe:a9fe]"),
        ("base_url", "http://[::127.0.0.1]"),
        ("start_after", "soon"),
        ("start_after", "9999-12-31"),
    ],
)
def test_bad_config_values_are_rejected(key: str, value: str) -> None:
    pull = source(SourceType.DISCOURSE, SourceMode.PULL)
    with pytest.raises(ValueError, match=key):
        check_source(pull.model_copy(update={"config": {**pull.config, key: value}}))


def test_a_public_host_passes_without_dns() -> None:
    pull = source(SourceType.DISCOURSE, SourceMode.PULL)
    public = {**pull.config, "base_url": "https://meta.discourse.org"}
    check_source(pull.model_copy(update={"config": public}))
