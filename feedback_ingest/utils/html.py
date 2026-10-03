import re
from html import unescape
from html.parser import HTMLParser
from typing import override

_INLINE_TAGS = frozenset(
    {"a", "b", "i", "em", "strong", "span", "code", "u", "s", "small", "sub", "sup"}
)
_HIDDEN_TAGS = frozenset({"script", "style"})


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    @override
    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN_TAGS:
            self.hidden_depth += 1
        if tag not in _INLINE_TAGS:
            self.parts.append(" ")

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS:
            self.hidden_depth = max(0, self.hidden_depth - 1)
        if tag not in _INLINE_TAGS:
            self.parts.append(" ")


def strip_tags(html: str) -> str:
    parser = _TextParser()
    try:
        parser.feed(html)
        parser.close()
    except AssertionError:  # stdlib raises this on an unknown marked section (<![x[ ... ]]>)
        return " ".join(unescape(re.sub(r"<[^>]*>", " ", html)).split())
    return " ".join("".join(parser.parts).split())
