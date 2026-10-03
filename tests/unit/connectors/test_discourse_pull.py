import pytest
from discourse_stub import BASE, CLOCK, DEADLINE, PULLER, StubHttp, pull_source, routes

from feedback_ingest.domain.errors import PermanentError


def test_pages_carry_titles_and_the_cursor_moves_on_the_final_page() -> None:
    http = StubHttp(routes([list(range(1, 51)), [51]]))
    src = pull_source()
    first, last = PULLER.pull(src, http, CLOCK, DEADLINE)
    assert len(first.payloads) == 50
    assert {p["topic_title"] for p in first.payloads} == {"Dark mode", "Login loop"}
    assert first.cursor == "2026-02-01"
    assert last.cursor == "2026-02-01T23:59:00"
    assert http.calls[0] == f"{BASE}/search.json after:2026-02-01 before:2026-03-02"
    records = [r for p in first.payloads for r in PULLER.transform(src, p)]
    assert sorted(int(r.external_id) for r in records) == list(range(1, 51))
    assert {r.title for r in records} == {"Dark mode", "Login loop"}


def test_posts_are_requested_twenty_ids_at_a_time() -> None:
    http = StubHttp(routes([list(range(1, 51))]))
    list(PULLER.pull(pull_source(), http, CLOCK, DEADLINE))
    post_calls = [call for call in http.calls if "posts.json" in call]
    assert [call.count("post_ids") for call in post_calls] == [20, 5, 20, 5]


def test_titles_come_from_search_topics_when_there_is_no_headline() -> None:
    [page] = PULLER.pull(pull_source(), StubHttp(routes([[1, 2]], topics=True)), CLOCK, DEADLINE)
    assert {p["topic_title"] for p in page.payloads} == {"Dark mode", "Login loop"}


def test_the_topic_title_wins_over_the_search_headline() -> None:
    found = routes([[1]], topics=True)
    search = found[f"{BASE}/search.json", "1"]
    assert isinstance(search, dict)
    search["posts"][0]["topic_title_headline"] = "Dark mode is…"
    [page] = PULLER.pull(pull_source(), StubHttp(found), CLOCK, DEADLINE)
    assert [p["topic_title"] for p in page.payloads] == ["Dark mode"]


def test_newest_timestamp_is_carried_to_an_empty_final_page() -> None:
    _, last = PULLER.pull(
        pull_source(), StubHttp(routes([list(range(1, 51)), []])), CLOCK, DEADLINE
    )
    assert last.cursor == "2026-02-01T00:49:00"


def test_short_pages_flagged_as_having_more_are_all_fetched() -> None:
    pages = list(
        PULLER.pull(pull_source(), StubHttp(routes([list(range(1, 21)), [21]])), CLOCK, DEADLINE)
    )
    assert [len(page.payloads) for page in pages] == [20, 1]


def test_a_quiet_window_advances_the_cursor_to_the_window_end() -> None:
    http = StubHttp(routes([[]]))
    [page] = PULLER.pull(pull_source(window_days=7), http, CLOCK, DEADLINE)
    assert page.payloads == []
    assert page.cursor == "2026-02-08T00:00:00"
    assert http.calls == [f"{BASE}/search.json after:2026-02-01 before:2026-02-08"]


def test_page_guard_stops_before_the_page_discourse_rejects() -> None:
    same = routes([[1], [1]])[f"{BASE}/search.json", "1"]
    found = routes([[1]]) | {(f"{BASE}/search.json", str(p)): same for p in range(1, 11)}
    found[f"{BASE}/search.json", "11"] = PermanentError("400 from search.json")
    pages = PULLER.pull(pull_source(), StubHttp(found), CLOCK, DEADLINE)
    cursors = [next(pages).cursor for _ in range(10)]
    assert set(cursors) == {"2026-02-01"}
    with pytest.raises(PermanentError, match="window exceeds 10 pages"):
        next(pages)


def test_the_cursor_never_moves_back_past_where_it_started() -> None:
    since = "2026-02-01T00:00:30"  # post 1 is 00:01, so newest minus the overlap is 00:00
    [page] = PULLER.pull(pull_source(cursor=since), StubHttp(routes([[1]])), CLOCK, DEADLINE)
    assert page.cursor == since
