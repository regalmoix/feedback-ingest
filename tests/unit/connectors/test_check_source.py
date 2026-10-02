import pytest
from connector_fixtures import source

from feedback_ingest.connectors.registry import PULLERS, check_source
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import Source


@pytest.mark.parametrize("source_type", sorted(set(SourceType) - PULLERS.keys()))
def test_pull_needs_a_puller(source_type: SourceType) -> None:
    with pytest.raises(ValueError, match="cannot pull"):
        check_source(source(source_type, SourceMode.PULL))


@pytest.mark.parametrize("key", PULLERS[SourceType.DISCOURSE].required_config)
def test_pull_needs_every_required_config_key(key: str) -> None:
    pull = source(SourceType.DISCOURSE, SourceMode.PULL)
    check_source(pull)
    missing = {k: v for k, v in pull.config.items() if k != key}
    with pytest.raises(ValueError, match=key):
        check_source(pull.model_copy(update={"config": missing}))


@pytest.mark.parametrize("secret", [None, ""])
def test_push_needs_a_secret(secret: str | None) -> None:
    push = source(SourceType.PLAYSTORE)
    check_source(push)
    with pytest.raises(ValueError, match="webhook_secret"):
        Source.model_validate(push.model_dump() | {"webhook_secret": secret})
