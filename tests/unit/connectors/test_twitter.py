from datetime import datetime

import pytest
from connector_fixtures import load, source
from pydantic import ValidationError

from feedback_ingest.connectors.twitter import TwitterConnector
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.metadata import TwitterMetadata

TWITTER = TwitterConnector()
SOURCE = source(SourceType.TWITTER)


def test_tweet_maps_to_a_record() -> None:
    [record] = TWITTER.transform(SOURCE, load(SourceType.TWITTER, "tweet"))
    created = datetime(2026, 3, 1, 18, 20)  # noqa: DTZ001  naive UTC is the storage convention
    assert record.kind is FeedbackKind.POST
    assert record.external_id == "1900000000000000001"
    assert record.text == "@exampleapp the new search is so much faster, nice work"
    assert (record.author, record.language, record.rating) == ("@sample_tweeter", "en", None)
    assert record.source_created_at == created
    assert record.metadata == TwitterMetadata(
        country="CA", retweets=3, likes=17, handle="@sample_tweeter"
    )


def test_edit_keeps_the_original_tweet_id_but_is_a_new_event() -> None:
    original, edited = load(SourceType.TWITTER, "tweet"), load(SourceType.TWITTER, "tweet_edited")
    [record] = TWITTER.transform(SOURCE, edited)
    assert record.external_id == "1900000000000000001"
    assert record.text.endswith("(but filters reset on back)")
    assert TWITTER.external_event_id(edited) == "1900000000000000002:2026-03-01T18:35:00"
    assert TWITTER.external_event_id(original) != TWITTER.external_event_id(edited)


def test_tweet_without_author_is_rejected() -> None:
    with pytest.raises(ValidationError, match="author"):
        TWITTER.transform(SOURCE, load(SourceType.TWITTER, "malformed"))
