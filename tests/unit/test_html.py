from feedback_ingest.utils.html import strip_tags


def test_strip_tags_handles_nesting_entities_and_whitespace() -> None:
    html = "<div><p>Hello <b>big <i>bold</i></b>\n  world</p><p>a &amp; b &lt;3 &#8212;</p></div>"
    assert strip_tags(html) == "Hello big bold world a & b <3 —"
    assert strip_tags("line<br>break") == "line break"
    assert strip_tags("   ") == ""
