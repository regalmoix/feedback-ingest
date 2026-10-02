from connector_fixtures import fixture_names

from feedback_ingest.connectors.registry import CONNECTORS, PULLERS
from feedback_ingest.domain.enums import SourceType
from feedback_ingest.domain.models import KIND_BY_SOURCE


def test_registry_has_one_connector_per_type_and_a_fixture_for_each() -> None:
    assert set(SourceType) == CONNECTORS.keys() == KIND_BY_SOURCE.keys() | {SourceType.CUSTOM}
    assert PULLERS.keys() <= CONNECTORS.keys()
    for t in SourceType:
        assert "malformed" in fixture_names(t)
