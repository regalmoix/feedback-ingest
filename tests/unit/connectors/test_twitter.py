from datetime import datetime

import pytest
from connector_fixtures import load, source

from feedback_ingest.connectors.twitter import TwitterConnector
from feedback_ingest.domain.enums import FeedbackKind, SourceType
from feedback_ingest.domain.errors import TransformError
from feedback_ingest.domain.metadata import TwitterMetadata

TWITTER = TwitterConnector()
SOURCE = source(SourceType.TWITTER)


def test_tweet_maps_to_a_record() -> None:
    [record] = TWITTER.transform(SOURCE, load(SourceType.TWITTER, "tweet"))
    assert record.kind is FeedbackKind.POST
    assert record.external_id == "1900000000000000001"
    assert record.text == "@exampleapp the new search is so much faster, nice work"
    assert (record.author, record.language, record.rating) == ("@sample_tweeter", "en", None)
    assert record.source_created_at == datetime(2026, 3, 1, 18, 20)
    assert record.metadata == TwitterMetadata(country="CA", retweets=3, likes=17)


def test_edit_keeps_the_original_tweet_id_but_is_a_new_event() -> None:
    original, edited = load(SourceType.TWITTER, "tweet"), load(SourceType.TWITTER, "tweet_edited")
    [record] = TWITTER.transform(SOURCE, edited)
    [first] = TWITTER.transform(SOURCE, original)
    assert record.external_id == "1900000000000000001"
    assert record.id == first.id
    assert record.text.endswith("(but filters reset on back)")
    assert TWITTER.external_event_id(edited) == "1900000000000000002:2026-03-01T18:35:00"
    assert TWITTER.external_event_id(original) != TWITTER.external_event_id(edited)


def test_tweet_without_edit_history_or_author_id_keys_on_its_own_id() -> None:
    payload = load(SourceType.TWITTER, "tweet") | {"author": {"username": "sample_tweeter"}}
    del payload["edit_history_tweet_ids"]
    [record] = TWITTER.transform(SOURCE, payload)
    assert record.external_id == "1900000000000000001"


def test_edit_history_without_the_tweet_itself_is_rejected() -> None:
    payload = load(SourceType.TWITTER, "tweet") | {"edit_history_tweet_ids": ["1"]}
    with pytest.raises(TransformError, match="edit_history"):
        TWITTER.transform(SOURCE, payload)
