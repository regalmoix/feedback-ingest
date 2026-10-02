import pytest
from connector_fixtures import fixture_names, source

from feedback_ingest.connectors.registry import (
    _ALL,
    CONNECTORS,
    PULLERS,
    check_source,
    connector_for,
    puller_for,
)
from feedback_ingest.domain.enums import SourceMode, SourceType


def test_registry_has_one_connector_per_type_and_a_fixture_for_each() -> None:
    assert set(SourceType) == CONNECTORS.keys()
    assert len(_ALL) == len(CONNECTORS)
    assert all(connector.source_type is t for t, connector in CONNECTORS.items())
    assert PULLERS.keys() <= CONNECTORS.keys()
    assert all(PULLERS[t] is CONNECTORS[t] for t in PULLERS)
    for t in SourceType:
        assert "malformed" in fixture_names(t)
        assert len(fixture_names(t)) >= 2


def test_check_source_rejects_pull_for_types_without_a_puller() -> None:
    check_source(source(SourceType.DISCOURSE, SourceMode.PULL))
    check_source(source(SourceType.PLAYSTORE))
    with pytest.raises(ValueError, match="cannot pull"):
        check_source(source(SourceType.PLAYSTORE, SourceMode.PULL))
    assert puller_for(source(SourceType.DISCOURSE)) is CONNECTORS[SourceType.DISCOURSE]
    assert connector_for(source(SourceType.TWITTER)) is CONNECTORS[SourceType.TWITTER]
