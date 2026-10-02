import hashlib
import json
from typing import Any


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def payload_hash(payload: dict[str, Any]) -> str:
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
