from collections.abc import Sequence
from typing import Any, Protocol


class HttpClient(Protocol):
    def get_json(self, url: str, params: Sequence[tuple[str, str]] = ()) -> dict[str, Any]: ...
