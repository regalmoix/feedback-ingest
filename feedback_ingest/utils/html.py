from html.parser import HTMLParser
from typing import override

_BLOCK_TAGS = frozenset({"br", "p", "div", "li", "tr", "blockquote", "pre", "h1", "h2", "h3"})


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    @override
    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag in _BLOCK_TAGS:
            self.parts.append(" ")


def strip_tags(html: str) -> str:
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    return " ".join("".join(parser.parts).split())
