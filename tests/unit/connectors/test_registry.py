import pytest
from connector_fixtures import fixture_names, source

from feedback_ingest.connectors.registry import _ALL, CONNECTORS, PULLERS, check_source
from feedback_ingest.domain.enums import SourceMode, SourceType
from feedback_ingest.domain.models import KIND_BY_SOURCE


def test_registry_has_one_connector_per_type_and_a_fixture_for_each() -> None:
    assert set(SourceType) == CONNECTORS.keys() == KIND_BY_SOURCE.keys()
    assert len(_ALL) == len(CONNECTORS)
    assert PULLERS.keys() <= CONNECTORS.keys()
    for t in SourceType:
        assert "malformed" in fixture_names(t)


def test_check_source_rejects_pull_for_types_without_a_puller() -> None:
    check_source(source(SourceType.DISCOURSE, SourceMode.PULL))
    check_source(source(SourceType.PLAYSTORE))
    with pytest.raises(ValueError, match="cannot pull"):
        check_source(source(SourceType.PLAYSTORE, SourceMode.PULL))


@pytest.mark.parametrize(
    ("config", "match"),
    [
        ({"start_after": "2026-02-01"}, "base_url"),
        ({"base_url": "https://forum.example.test"}, "start_after"),
        ({"base_url": "https://forum.example.test", "start_after": "soon"}, "start_after"),
    ],
)
def test_check_source_rejects_bad_pull_config(config: dict[str, str], match: str) -> None:
    pull = source(SourceType.DISCOURSE, SourceMode.PULL).model_copy(update={"config": config})
    with pytest.raises(ValueError, match=match):
        check_source(pull)
