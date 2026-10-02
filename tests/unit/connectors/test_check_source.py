import pytest
from connector_fixtures import source

from feedback_ingest.connectors.registry import PULLERS, check_source
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source


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
        ("base_url", "forum.example.test"),
        ("base_url", "ftp://forum.example.test"),
        ("base_url", "https://user:pw@forum.example.test"),
        ("start_after", "soon"),
    ],
)
def test_bad_config_values_are_rejected(key: str, value: str) -> None:
    pull = source(SourceType.DISCOURSE, SourceMode.PULL)
    with pytest.raises(ValueError, match=key):
        check_source(pull.model_copy(update={"config": {**pull.config, key: value}}))


@pytest.mark.parametrize("secret", [None, ""])
def test_push_needs_a_secret(secret: str | None) -> None:
    push = source(SourceType.PLAYSTORE)
    check_source(push)
    with pytest.raises(ValueError, match="webhook_secret"):
        Source.model_validate(push.model_dump() | {"webhook_secret": secret})
