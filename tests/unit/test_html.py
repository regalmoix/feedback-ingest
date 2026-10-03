from feedback_ingest.utils.html import strip_tags


def test_strip_tags_handles_nesting_entities_and_whitespace() -> None:
    html = "<div><p>Hello <b>big <i>bold</i></b>\n  world</p><p>a &amp; b &lt;3 &#8212;</p></div>"
    assert strip_tags(html) == "Hello big bold world a & b <3 —"
    assert strip_tags("line<br>break") == "line break"
    assert strip_tags("   ") == ""


def test_strip_tags_flushes_a_trailing_entity() -> None:
    assert strip_tags("tom &amp; jerry &") == "tom & jerry &"


def test_strip_tags_hides_script_and_style_and_breaks_on_non_inline_tags() -> None:
    assert strip_tags("<style>p { color: red }</style><p>hi</p><script>x()</script>") == "hi"
    assert strip_tags("<h4>T</h4>body") == "T body"
    assert strip_tags("<tr><td>a</td><td>b</td></tr>") == "a b"


def test_a_stray_closing_script_tag_does_not_hide_the_rest() -> None:
    assert strip_tags("before</script>after") == "before after"


def test_an_unknown_marked_section_does_not_raise() -> None:
    assert strip_tags("<![bogus[ x ]]> hi &amp; bye") == "hi & bye"
