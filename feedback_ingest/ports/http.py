from typing import Any, Protocol


class HttpClient(Protocol):
    def get_json(self, url: str, params: dict[str, str]) -> dict[str, Any]: ...
